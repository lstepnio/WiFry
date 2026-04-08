# RPi 5 Performance & Efficiency Guide for Packet Capture

**Status:** Draft
**Date:** 2026-04-07
**Companion specs:** `capture-v2-spec.md`, `ai-analysis-framework.md`

---

## 1. Hardware Constraints: Know Your Budget

The Raspberry Pi 5 is not a server. Every design choice starts from these hard numbers.

| Resource | RPi 5 (8 GB) | Practical budget for capture | Why the limit |
|---|---|---|---|
| CPU | 4x Cortex-A76 @ 2.4 GHz | ~1 core sustained for capture + post-process | Other 3 cores run AP, NAT, FastAPI, DNS, hostapd |
| RAM | 8 GB LPDDR4X | 200 MB total for capture subsystem | OS ~500 MB, Python ~150 MB, AP stack ~100 MB, headroom needed |
| Disk write bandwidth | SD: ~25 MB/s sequential, USB 3: ~300 MB/s | SD: ~10 MB/s sustained (leave headroom for journal/logs) | SD wear amplification; high write load kills cards |
| Disk read bandwidth | SD: ~45 MB/s, USB 3: ~400 MB/s | Full bandwidth OK for burst post-processing reads | Reads are non-destructive |
| Storage | 32-128 GB SD typical | 500 MB captures + 200 MB summaries/analyses | SD cards are small and expensive |
| Network throughput (AP) | ~300 Mbps (WiFi 6E theoretical) | Capture rate matches network rate | Can't drop packets during capture |
| Thermal | Throttles at 85 C | Sustained CPU = thermal throttle in ~5 min without heatsink | Affects post-processing latency |

### The Core Tension

Capture demands **sustained I/O** (write every packet to disk in real time). Post-processing demands **burst CPU** (tshark dissects every packet in memory). You cannot do both at the same time on the same core without degrading capture fidelity.

---

## 2. Major Performance Risks

### Risk 1: tshark for capture wastes 30-80 MB RAM per process

**Problem:** `tshark -i wlan0 -w file.pcap` loads all protocol dissectors even when only writing raw packets. On RPi 5, this means 30-80 MB RSS per capture process. With 2 concurrent captures, that is 160 MB of RAM doing nothing useful.

**Impact:** Reduces headroom for post-processing, may trigger OOM killer under load.

**Mitigation:** Use `dumpcap` for capture. It is the same packet engine Wireshark uses internally, but without dissectors. RSS is ~5 MB.

```
# Bad: loads all dissectors just to write raw packets
tshark -i wlan0 -w /captures/test.pcap

# Good: raw capture only, minimal memory
dumpcap -i wlan0 -w /captures/test.pcap
```

### Risk 2: Post-processing and capture competing for the same core

**Problem:** If tshark post-processing (stat extraction) runs while dumpcap is still capturing, both compete for CPU. tshark stat extraction reads the entire pcap and dissects every packet — this is CPU-intensive. If dumpcap can not keep up with the packet rate during this time, packets are dropped silently.

**Impact:** Packet loss in capture data. Corrupted analysis.

**Mitigation:**
- Never run post-processing while a capture is actively writing to the same pcap.
- Post-processing starts only after capture completes and the file is closed.
- Use `nice -n 10` and `ionice -c2 -n 7` on post-processing tshark to deprioritize it.
- Serialize post-processing: one pipeline at a time (`asyncio.Lock`).

### Risk 3: SD card write amplification and wear

**Problem:** SD cards use flash translation layers that amplify writes. A 100 MB capture may cause 200-400 MB of actual flash writes due to page-level erase/write cycles. Sustained capture (background ring buffer) will kill a consumer SD card in months.

**Impact:** SD card failure, data loss, bricked appliance.

**Mitigation:**
- Default captures are short (30-120 seconds). Not continuous.
- Background capture (always-on ring buffer) requires explicit opt-in.
- Recommend USB 3 storage for background capture — NVMe over USB or a quality USB flash drive.
- Use `noatime` mount option for the captures volume to avoid metadata writes on reads.
- Ring buffer segment size of 10 MB matches SD card erase block alignment.

### Risk 4: Large pcap files blowing RAM during post-processing

**Problem:** `tshark -r large.pcap -q -z conv,tcp` must read and dissect the entire file. A 100 MB pcap with 500K+ packets can push tshark to 200-400 MB RSS.

**Impact:** OOM kill of tshark or the backend process. Stalled post-processing.

**Mitigation:**
- Cap pcap files at 100 MB (ring buffer: 10 segments x 10 MB).
- Process ring buffer segments individually for stats, then merge numerical results, instead of merging pcap first and processing the monolith. (Advanced optimization for phase 2.)
- Set `ulimit -v` on tshark subprocess to 512 MB as a hard kill boundary.
- Monitor `/proc/{pid}/status` VmRSS during post-processing; kill if >400 MB.

### Risk 5: Unbounded disk growth from capture accumulation

**Problem:** Without retention policy, captures accumulate until the SD card is full. When the SD card fills, the AP stops logging, DNS stops caching, and the system degrades.

**Impact:** Appliance stops working.

**Mitigation:**
- Auto-retention: max 20 captures, 500 MB total, 7-day max age.
- Pre-check before starting capture: require 200 MB free on the captures volume.
- Mid-capture monitor: check free space every 10 seconds during capture; force-stop if <50 MB free.
- Retention enforcement runs after every capture completion.

### Risk 6: Concurrent tshark stat queries thrashing the disk

**Problem:** Post-processing runs 5-8 tshark queries, each reading the full pcap. That is 5-8 sequential full reads of a 100 MB file = 500-800 MB of read I/O. On SD card, this takes 11-18 seconds. If multiple captures finish simultaneously, the reads interleave and thrash.

**Impact:** Post-processing takes 30-60 seconds instead of 10-15.

**Mitigation:**
- Serialize post-processing with an `asyncio.Lock` (only one pipeline at a time).
- Read the pcap into the OS page cache on the first query; subsequent queries hit cache.
  Hint: run `cat {pcap} > /dev/null` before the first tshark query. This sequential read is faster than tshark's random-ish access pattern.
- On systems with enough RAM (8 GB RPi 5), a 100 MB file fits in page cache easily.

---

## 3. Tool Decisions

### 3.1 dumpcap vs tshark

| | dumpcap | tshark |
|---|---|---|
| **Use for** | Capture to disk | Post-processing stat extraction |
| **RAM** | ~5 MB | 30-80 MB (50-400 MB for large files) |
| **CPU during capture** | ~2-5% of one core at 10 Mbps | ~15-30% of one core at 10 Mbps |
| **Ring buffer** | Native: `-b filesize:10240 -b files:10` | Supported but wastes RAM on dissectors |
| **BPF filter** | Yes (`-f "tcp port 443"`) | Yes |
| **Output format** | pcap or pcapng | pcap or pcapng |

**Decision:** dumpcap captures. tshark analyzes. No exceptions.

### 3.2 Live decode vs post-process decode

**Live decode** means running tshark with display filters during capture to extract stats in real time. **Post-process decode** means capturing raw packets with dumpcap, then running tshark on the completed file.

| | Live decode | Post-process |
|---|---|---|
| RAM during capture | 80-200 MB (dissectors + state tables) | 5 MB (dumpcap only) |
| CPU during capture | 30-60% of one core | 2-5% of one core |
| Packet drop risk | High at >50 Mbps on RPi 5 | Low (raw write only) |
| Time-to-first-stat | Immediate | Capture duration + 5-15s |
| Complexity | High (streaming parsers) | Low (batch queries on file) |

**Decision:** Post-process only. Live decode is a luxury the RPi 5 cannot afford.

The one exception: **live packet count and file size** can be estimated without decoding, by polling file size every second. This is cheap and gives the user progress feedback.

### 3.3 pcap vs pcapng

| | pcap (libpcap) | pcapng |
|---|---|---|
| File size | Slightly smaller (simpler header) | ~2-5% larger (richer metadata) |
| Per-packet metadata | Timestamp + captured length | Timestamp + length + interface + comments + options |
| Multi-interface | Not supported | Native (Interface Description Blocks) |
| Tool compatibility | Universal | Wireshark, tshark, dumpcap, scapy. Some older tools don't read it. |
| Write performance | Identical | Identical (both sequential writes) |

**Decision:** pcap for MVP. Switch to pcapng in phase 3 when multi-interface capture or per-packet annotations are needed. dumpcap defaults to pcapng anyway, so use `-F pcap` explicitly for now.

```bash
dumpcap -i wlan0 -F pcap -b filesize:10240 -b files:10 -w /captures/{id}.pcap
```

### 3.4 Compression timing

**Never compress during capture.** CPU overhead of compression competes with packet capture. Packets will be dropped.

**Compress after post-processing, if at all:**

| Strategy | When | CPU cost | Space saving | Recommendation |
|---|---|---|---|---|
| No compression | — | 0 | 0% | Default for captures <50 MB |
| gzip post-capture | After stats extracted | ~10s for 100 MB on RPi 5 | ~60-70% | Only for archival/export |
| zstd post-capture | After stats extracted | ~4s for 100 MB on RPi 5 | ~65-75% | Better than gzip if installed |
| Delete pcap, keep summary only | After AI analysis | 0 | ~99% | "Stats-only mode" (phase 2) |

**Decision:** No compression by default. Pcap stays uncompressed for fast re-analysis. Offer a "compress and archive" option for captures the user wants to keep but not re-analyze. Stats-only mode (delete pcap, keep summary JSON) is the most aggressive and most useful space saver.

### 3.5 File rotation strategy

**Ring buffer with dumpcap:**

```bash
dumpcap -i wlan0 -F pcap \
  -b filesize:10240 \   # 10 MB per segment
  -b files:10 \         # max 10 segments (100 MB total cap)
  -f "tcp port 443" \
  -w /var/lib/wifry/captures/{id}.pcap
```

dumpcap automatically names segments: `{id}_00001_{timestamp}.pcap`, `{id}_00002_{timestamp}.pcap`, etc. When segment 11 would be created, segment 1 is deleted.

**On capture stop:**

```bash
# Merge remaining segments into single file
mergecap -w /var/lib/wifry/captures/{id}.pcap \
  /var/lib/wifry/captures/{id}_*.pcap

# Delete segments after successful merge
rm /var/lib/wifry/captures/{id}_*_*.pcap
```

**Why merge?** Users expect a single pcap to download. tshark stat queries on a single file are simpler than cross-file aggregation. mergecap is streaming (low RAM) and fast (~2 seconds for 100 MB).

**When NOT to merge:** If the merged file would exceed 200 MB, keep segments and run stats on each individually. This is an edge case for very long custom captures.

### 3.6 Segment sizing

| Segment size | Segments at 100 MB cap | Write flush frequency | Pros | Cons |
|---|---|---|---|---|
| 1 MB | 100 | Every ~0.5s at 20 Mbps | Fine-grained ring buffer; minimal data loss on crash | Too many files; mergecap overhead; filesystem metadata churn |
| 5 MB | 20 | Every ~2.5s at 20 Mbps | Good balance | Slightly more files than 10 MB |
| **10 MB** | **10** | **Every ~5s at 20 Mbps** | **Good balance; matches SD erase block alignment; manageable file count** | **5 seconds of data lost if segment not flushed on crash** |
| 25 MB | 4 | Every ~12s at 20 Mbps | Fewer files | Coarse ring buffer; more data lost on crash; 4 segments gives poor rolling coverage |
| 50 MB | 2 | Every ~25s at 20 Mbps | Minimal files | Basically not a ring buffer; defeats the purpose |

**Decision:** 10 MB segments, 10 files max. This gives 100 MB total cap with 10 rotation points.

---

## 4. Resource Guardrails and Backpressure

### 4.1 Pre-Capture Checks

```python
async def preflight_check() -> list[str]:
    """Return list of blocking reasons, empty if OK to start."""
    reasons = []

    # Concurrent capture limit
    running = sum(1 for c in _captures.values() if c.status == CaptureStatus.RUNNING)
    if running >= MAX_CONCURRENT_CAPTURES:  # 2
        reasons.append(f"Maximum {MAX_CONCURRENT_CAPTURES} concurrent captures reached")

    # Disk space
    usage = shutil.disk_usage(CAPTURES_DIR)
    free_mb = usage.free / (1024 * 1024)
    if free_mb < MIN_FREE_SPACE_MB:  # 200
        reasons.append(f"Insufficient disk space: {free_mb:.0f} MB free, need {MIN_FREE_SPACE_MB} MB")

    # Memory
    mem = psutil.virtual_memory()
    if mem.available < MIN_FREE_RAM_BYTES:  # 256 MB
        reasons.append(f"Insufficient RAM: {mem.available // (1024*1024)} MB available")

    # CPU load (5-min average)
    load_avg = os.getloadavg()[1]  # 5-minute average
    if load_avg > CPU_LOAD_THRESHOLD:  # 3.0 (75% of 4 cores)
        reasons.append(f"System under heavy load: {load_avg:.1f} (threshold {CPU_LOAD_THRESHOLD})")

    return reasons
```

### 4.2 Mid-Capture Monitoring

The capture monitor task (polling every second) should check:

```python
async def _monitor_capture(capture_id: str):
    while capture_is_running(capture_id):
        # Update file size and segment count for UI
        update_live_stats(capture_id)

        # Disk space check every 10 seconds
        if iteration % 10 == 0:
            free_mb = shutil.disk_usage(CAPTURES_DIR).free / (1024 * 1024)
            if free_mb < EMERGENCY_FREE_SPACE_MB:  # 50 MB
                logger.error("Emergency stop: disk nearly full (%d MB free)", free_mb)
                await stop_capture(capture_id, reason="disk_space_emergency")
                break

        await asyncio.sleep(1)
```

### 4.3 Post-Processing Resource Limits

```python
# Serialize post-processing: one pipeline at a time
_postprocess_lock = asyncio.Lock()

async def run_postprocessing(capture_id: str):
    async with _postprocess_lock:
        # Pre-warm page cache (sequential read is faster than tshark's access pattern)
        await run_shell(f"cat {pcap_path} > /dev/null", timeout=30)

        for query in pack_queries:
            result = await run_shell(
                f"nice -n 10 ionice -c2 -n7 tshark -r {pcap_path} {query}",
                timeout=60,
            )
            # Parse result...

        # Enforce total post-processing timeout
        # (handled by asyncio.wait_for around the whole block)
```

**Key settings:**

| Parameter | Value | Rationale |
|---|---|---|
| `nice -n 10` | Lower CPU priority | Don't starve AP, NAT, FastAPI |
| `ionice -c2 -n 7` | Best-effort, low priority I/O | Don't block journal writes |
| Per-query timeout | 60 seconds | Single query on 100 MB should finish in ~10s; 60s is generous |
| Total pipeline timeout | 5 minutes | Full pack (8 queries) should finish in ~90s; 5 min is safety |
| Post-process lock | 1 concurrent | Prevent 2 pipelines thrashing disk |

### 4.4 Backpressure Signals

When the system is under pressure, propagate backpressure to the user rather than silently degrading:

| Signal | Detection | User-facing message |
|---|---|---|
| Disk space low | `free < 200 MB` | "Low disk space. Clear old captures or connect USB storage before starting a new capture." |
| RAM pressure | `available < 256 MB` | "System memory low. Close unused features or wait for post-processing to complete." |
| CPU overloaded | 5-min load avg > 3.0 | "System is busy. Capture quality may be reduced. Consider stopping other operations." |
| Post-processing queue | >2 captures waiting | "Post-processing backlog. Results will be available shortly." |
| SD card slow | Write rate <5 MB/s measured | "Storage is slow. Consider using USB storage for captures." |

### 4.5 systemd Resource Limits

Add to `wifry-backend.service`:

```ini
[Service]
# Prevent runaway memory from killing the system
MemoryMax=2G
MemoryHigh=1.5G

# Don't let capture + post-processing starve other services
CPUWeight=80

# Prevent file descriptor leaks from zombie tshark processes
LimitNOFILE=4096

# OOM score: prefer killing wifry over system services
OOMScoreAdjust=200
```

This lets the kernel kill the WiFry backend before it kills hostapd, dnsmasq, or sshd.

---

## 5. Post-Processing Scheduling

### 5.1 Pipeline Stages and Timing

```
Capture completes (dumpcap exits)
       │
       ├─ 0s: Fix file permissions (chown/chmod)
       │
       ├─ 0.1s: Merge ring buffer segments (mergecap)
       │         ~2s for 100 MB; serial I/O, low CPU
       │
       ├─ 2s: Delete segments (rm)
       │
       ├─ 2.1s: Pre-warm page cache (cat > /dev/null)
       │         ~3s for 100 MB on SD card
       │
       ├─ 5s: Run tshark stat queries (sequential, nice'd)
       │       5-8 queries × ~2-3s each = 10-24s typical
       │
       ├─ 30s: Build CaptureSummary JSON
       │        <100ms (Python dict construction)
       │
       ├─ 30.1s: Run interest detection (threshold checks)
       │          <100ms (numeric comparisons)
       │
       ├─ 30.2s: Save {id}.summary.json
       │
       ├─ 30.3s: Enforce retention policy
       │          Delete oldest captures if over limits
       │
       └─ DONE. Total: ~30-45 seconds typical for 100 MB capture.
```

AI analysis is NOT part of this pipeline. It runs on-demand when the user clicks "Get AI Diagnosis."

### 5.2 Query Ordering Optimization

Not all tshark queries are equal. Order them by value-per-second:

| Query | Typical time (100 MB) | Value to user | Run order |
|---|---|---|---|
| `-z io,phs` (protocol hierarchy) | ~2s | High (overview) | 1st — show protocols immediately |
| `-z expert` (retx, errors) | ~3s | High (health indicator) | 2nd — powers health badge |
| `-z io,stat,1` (throughput/sec) | ~2s | High (throughput chart) | 3rd — powers throughput graph |
| `-z conv,tcp` (conversations) | ~3s | Medium (flow table) | 4th |
| DNS field extraction | ~2s | Medium (DNS table) | 5th |
| `-z endpoints,ip` | ~2s | Low (IP list) | 6th |
| TLS ClientHello extraction | ~2s | Low (TLS table) | 7th |
| ICMP extraction | ~1s | Pack-dependent | 8th |

**Progressive rendering:** Save partial summary after each query completes. The frontend polls `/captures/{id}/summary` and renders whatever's available. The user sees protocol breakdown within 5 seconds of capture completion, not after 30 seconds.

```python
async def extract_stats_progressive(capture_id: str, pcap_path: Path, pack: str):
    summary = CaptureSummary(meta=build_meta(capture_id, pcap_path))

    for query_fn in get_ordered_queries(pack):
        try:
            section = await asyncio.wait_for(query_fn(pcap_path), timeout=60)
            setattr(summary, section.field_name, section.data)
            save_summary(capture_id, summary)  # overwrite with more data
        except asyncio.TimeoutError:
            logger.warning("Query %s timed out for capture %s", query_fn.name, capture_id)
            # Continue with remaining queries — partial data is better than none
```

### 5.3 Skip Unnecessary Queries

Each analysis pack defines which queries to run. Don't run DNS extraction for a connectivity pack that filtered on `icmp only`. Don't run ICMP extraction for a DNS pack.

```python
PACK_QUERIES = {
    "connectivity": ["io_phs", "expert", "icmp", "dns_fields", "endpoints"],
    "dns":          ["dns_fields", "io_stat"],
    "https":        ["io_phs", "expert", "io_stat", "conv_tcp", "tls_hello"],
    "streaming":    ["io_phs", "expert", "io_stat", "conv_tcp", "dns_fields"],
    "security":     ["io_phs", "expert", "conv_tcp", "conv_udp", "endpoints", "dns_fields", "tls_hello"],
    "custom":       ["io_phs", "expert", "io_stat", "conv_tcp", "dns_fields"],  # general set
}
```

---

## 6. Fast Summary vs Deep Summary

### 6.1 Two Tiers

| Tier | What it provides | Time to produce | Cost |
|---|---|---|---|
| **Fast summary** | Protocol breakdown, health badge, throughput chart, top conversations | 10-15s after capture | Free (local tshark) |
| **Deep summary** | AI interpretation, findings with evidence, likely causes, next steps | +3-10s after user request | $0.01-0.03 per AI call |

The fast summary is always available. It is the stats dashboard. It answers "what happened in this capture?" with numbers and charts.

The deep summary is on-demand. It answers "what does this mean?" and "what should I do?" with AI interpretation.

### 6.2 Fast Summary: What to Prioritize

Show the user the most useful information first:

1. **Health badge** (green/yellow/red) — derived from interest detection thresholds. Available in <1 second after stats extraction begins.
2. **Protocol pie chart** — from `io,phs`. Available in ~5 seconds.
3. **Retransmission rate** — from `expert`. Available in ~8 seconds.
4. **Throughput timeline graph** — from `io,stat,1`. Available in ~10 seconds.
5. **Top 5 conversations table** — from `conv,tcp`. Available in ~13 seconds.
6. **DNS summary** — from field extraction. Available in ~15 seconds.

Everything above is deterministic. No AI. No API call. No cost.

### 6.3 Deep Summary: When to Suggest It

The UI should actively suggest AI analysis when the fast summary reveals interesting findings:

```
if overall_health == "unhealthy":
    show: "Issues detected. [Get AI Diagnosis] for detailed analysis and recommendations."
elif overall_health == "degraded":
    show: "Some concerns found. [Get AI Diagnosis] to understand potential impact."
else:
    show: "[Get AI Diagnosis]"  # available but not promoted
```

---

## 7. Concurrency and Worker Patterns

### 7.1 Architecture

```
FastAPI event loop (main thread)
    │
    ├── /captures/start  → spawns dumpcap subprocess
    │                      starts _monitor_capture() task
    │
    ├── /captures/stop   → sends SIGTERM to dumpcap
    │                      _monitor_capture() detects exit
    │                      triggers post-processing
    │
    ├── /captures/{id}/summary → reads summary.json from disk
    │
    └── /captures/{id}/analyze → starts AI call (async HTTP)

Subprocess pool (managed by asyncio):
    ├── dumpcap process (0-2 concurrent)
    ├── tshark post-processing (0-1 concurrent, serialized by lock)
    └── mergecap (0-1 concurrent, part of post-processing)

Locks:
    ├── _capture_lock: asyncio.Lock — protects capture registry mutations
    ├── _postprocess_lock: asyncio.Lock — serializes stat extraction
    └── _capture_semaphore: asyncio.Semaphore(2) — limits concurrent captures
```

### 7.2 Rules

1. **dumpcap processes are fire-and-forget.** Launch via `asyncio.create_subprocess_exec`, store the handle, monitor via a background task. Don't `await` the process in the request handler — that would block the API.

2. **Post-processing is serialized.** One `asyncio.Lock` ensures only one tshark stat extraction runs at a time. This prevents disk thrashing and keeps peak memory predictable.

3. **AI calls are async HTTP.** They don't block the event loop. Multiple AI calls can be in-flight simultaneously (they're just network I/O). Rate-limit at the application level (1 per 30 seconds per capture).

4. **Never use threads for subprocess management.** asyncio subprocess handling is sufficient and avoids GIL contention with the FastAPI event loop.

5. **Never use multiprocessing.** The RPi 5 has 4 cores but they are already committed. Spawning Python worker processes wastes RAM on interpreter copies.

6. **Process cleanup on shutdown.** When the backend receives SIGTERM, iterate all tracked processes and send SIGTERM. Wait 5 seconds. Send SIGKILL to survivors. This prevents zombie dumpcap processes.

### 7.3 Stale Process Recovery

On backend startup, check for orphaned processes:

```python
async def reconcile_on_startup():
    """Mark captures as ERROR if the backend restarted while they were RUNNING."""
    for capture in load_all_captures():
        if capture.status == CaptureStatus.RUNNING:
            # Backend restarted — dumpcap process is gone
            capture.status = CaptureStatus.ERROR
            capture.error = "Backend restarted during capture"
            save_capture(capture)

            # Check if pcap file exists and has data
            if capture.pcap_path and Path(capture.pcap_path).exists():
                size = Path(capture.pcap_path).stat().st_size
                if size > 0:
                    capture.status = CaptureStatus.STOPPED
                    capture.error = "Backend restarted; capture data recovered"
                    # Trigger post-processing on recovered captures
                    asyncio.create_task(run_postprocessing(capture.id))
```

---

## 8. Cleanup and Pruning Policy

### 8.1 Retention Rules

| Rule | Threshold | Enforcement timing |
|---|---|---|
| Max completed captures | 20 | After every capture completion |
| Max total capture storage | 500 MB | After every capture completion |
| Max capture age | 7 days | After every capture completion + daily cron |
| Session-linked captures | Exempt while session active | Pruned when session is discarded |
| Running captures | Never pruned | — |
| Summary JSON files | Pruned with their capture | — |
| Analysis JSON files | Pruned with their capture | — |

### 8.2 Pruning Implementation

```python
async def enforce_retention():
    """Delete oldest captures until within retention limits."""
    captures = sorted(
        [c for c in load_all_captures() if c.status not in (CaptureStatus.RUNNING,)],
        key=lambda c: c.started_at or "",
    )

    # Exclude session-linked captures
    active_sessions = get_active_session_ids()
    prunable = [c for c in captures if not is_linked_to_active_session(c.id, active_sessions)]

    deleted = []

    # Age-based: delete anything older than 7 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for c in prunable:
        if c.started_at and datetime.fromisoformat(c.started_at) < cutoff:
            await delete_capture_files(c.id)
            deleted.append(c)

    prunable = [c for c in prunable if c not in deleted]

    # Count-based: keep newest 20
    while len(prunable) > MAX_CAPTURE_COUNT:
        oldest = prunable.pop(0)
        await delete_capture_files(oldest.id)
        deleted.append(oldest)

    # Size-based: keep under 500 MB
    total_bytes = sum(get_capture_disk_usage(c.id) for c in prunable)
    while total_bytes > MAX_CAPTURE_BYTES and prunable:
        oldest = prunable.pop(0)
        freed = get_capture_disk_usage(oldest.id)
        await delete_capture_files(oldest.id)
        deleted.append(oldest)
        total_bytes -= freed

    if deleted:
        freed_mb = sum(get_capture_disk_usage(c.id) for c in deleted) / (1024 * 1024)
        logger.info("Retention: pruned %d captures, freed %.1f MB", len(deleted), freed_mb)
        # Emit notification to UI
        emit_notification(f"Auto-cleaned {len(deleted)} old capture(s) to free {freed_mb:.0f} MB")
```

### 8.3 Daily Maintenance Task

Beyond post-capture retention enforcement, run a daily cleanup:

```python
async def daily_maintenance():
    """Run once per day via background scheduler."""
    # 1. Age-based retention
    await enforce_retention()

    # 2. Clean orphaned segment files (segments without a parent capture)
    for seg_file in CAPTURES_DIR.glob("*_*_*.pcap"):
        capture_id = seg_file.name.split("_")[0]
        if not (CAPTURES_DIR / f"{capture_id}.json").exists():
            seg_file.unlink()
            logger.info("Cleaned orphaned segment: %s", seg_file.name)

    # 3. Clean orphaned analysis files (analysis without a capture)
    for analysis_file in CAPTURES_DIR.glob("*.analysis.json"):
        capture_id = analysis_file.stem.replace(".analysis", "")
        if not (CAPTURES_DIR / f"{capture_id}.json").exists():
            analysis_file.unlink()

    # 4. Clean orphaned summary files
    for summary_file in CAPTURES_DIR.glob("*.summary.json"):
        capture_id = summary_file.stem.replace(".summary", "")
        if not (CAPTURES_DIR / f"{capture_id}.json").exists():
            summary_file.unlink()
```

---

## 9. Benchmarking and Load Testing

### 9.1 Benchmark Suite

Create `backend/tests/benchmarks/` with these tests, run on actual RPi 5 hardware:

#### Capture Engine Benchmarks

| Test | Procedure | Target | Failure threshold |
|---|---|---|---|
| **dumpcap RSS** | Start dumpcap, measure VmRSS after 10s | <10 MB | >20 MB |
| **tshark RSS** | Start tshark -w, measure VmRSS after 10s | baseline only | — |
| **Capture write throughput** | dumpcap on 50 Mbps traffic for 30s, check dropped packets | 0 drops | >0 drops on SD |
| **Segment rotation** | 10 MB segments, verify rotation occurs correctly | Clean rotation | Overlapping writes |
| **mergecap time** | Merge 10 x 10 MB segments | <5s | >10s |
| **mergecap RAM** | VmRSS of mergecap during 100 MB merge | <20 MB | >50 MB |

#### Post-Processing Benchmarks

| Test | Procedure | Target | Failure threshold |
|---|---|---|---|
| **io,phs time** | tshark on 50 MB pcap | <3s | >10s |
| **conv,tcp time** | tshark on 50 MB pcap | <5s | >15s |
| **expert time** | tshark on 50 MB pcap | <5s | >15s |
| **io,stat,1 time** | tshark on 50 MB pcap | <3s | >10s |
| **DNS extraction time** | tshark on 50 MB pcap with ~500 DNS queries | <3s | >10s |
| **Full pipeline time** | All pack queries on 50 MB pcap | <30s | >90s |
| **tshark peak RSS** | VmRSS during conv,tcp on 100 MB pcap | <200 MB | >400 MB |
| **Progressive save latency** | Time from capture stop to first summary.json write | <8s | >20s |

#### System Impact Benchmarks

| Test | Procedure | Target | Failure threshold |
|---|---|---|---|
| **AP throughput during capture** | iperf3 through AP while dumpcap captures | <5% throughput drop | >15% drop |
| **AP latency during capture** | ping through AP while dumpcap captures | <2ms added latency | >10ms added |
| **AP throughput during post-processing** | iperf3 through AP while tshark runs stats | <10% throughput drop | >25% drop |
| **Backend API latency during post-processing** | Measure /health response time while tshark runs | <100ms | >500ms |
| **Thermal during sustained capture** | Temperature after 5 min of capture + post-process | <75 C with heatsink | >80 C |

#### Stress Tests

| Test | Procedure | Expected behavior |
|---|---|---|
| **Rapid start/stop** | Start and stop 10 captures in 30 seconds | No zombie processes, all captures have metadata |
| **Max concurrent** | Start 3 captures simultaneously | 3rd is rejected with 429, first 2 complete normally |
| **Disk full** | Fill disk to <50 MB free, start capture | Pre-flight rejects; existing captures auto-stop |
| **OOM simulation** | cgroup-limit to 256 MB, run post-processing on 100 MB pcap | tshark killed, capture marked as error, backend survives |
| **Backend crash during capture** | kill -9 backend while capture runs | On restart: capture marked as STOPPED, post-processing runs on recovered pcap |
| **Power loss simulation** | kill -9 dumpcap mid-write | Partial segments exist; metadata shows ERROR; no data corruption beyond last segment |

### 9.2 Benchmark Harness

```bash
#!/bin/bash
# benchmarks/run_rpi5.sh — run on actual RPi 5 hardware
set -euo pipefail

PCAP_50MB="testdata/sample_50mb.pcap"
PCAP_100MB="testdata/sample_100mb.pcap"
RESULTS="benchmark_results_$(date +%Y%m%d_%H%M%S).json"

echo "RPi 5 Capture Benchmark Suite"
echo "============================="
echo "Temperature: $(vcgencmd measure_temp)"
echo "Free RAM: $(free -m | awk '/Mem:/{print $4}') MB"
echo "Free disk: $(df -m /var/lib/wifry | awk 'NR==2{print $4}') MB"

# Test 1: mergecap time
echo -n "mergecap 10x10MB: "
TIME=$( { time mergecap -w /tmp/merged.pcap testdata/seg_*.pcap; } 2>&1 | grep real | awk '{print $2}' )
echo "$TIME"

# Test 2: tshark io,phs on 50MB
echo -n "tshark io,phs 50MB: "
TIME=$( { time tshark -r "$PCAP_50MB" -q -z io,phs > /dev/null; } 2>&1 | grep real | awk '{print $2}' )
echo "$TIME"

# Test 3: tshark peak RSS
echo -n "tshark peak RSS conv,tcp 100MB: "
/usr/bin/time -v tshark -r "$PCAP_100MB" -q -z conv,tcp > /dev/null 2> /tmp/tshark_mem.txt
RSS=$(grep "Maximum resident" /tmp/tshark_mem.txt | awk '{print $NF}')
echo "${RSS} KB"

# ... continue for all benchmarks
```

### 9.3 Generating Test pcap Files

```bash
# Generate a 50 MB pcap with realistic traffic patterns
# (run on a machine with network access, transfer to RPi)
tshark -i eth0 -a filesize:51200 -w testdata/sample_50mb.pcap

# Or generate synthetic traffic:
tcpreplay --intf1=lo --mbps=50 --duration=10 testdata/template.pcap
```

For repeatable benchmarks, commit a small (~5 MB) test pcap to the repo and use it to generate larger files via `tcpreplay` loops.

---

## 10. Anti-Patterns

### Anti-Pattern 1: Running tshark for capture when dumpcap suffices

**Symptom:** 30-80 MB RSS per capture process instead of 5 MB.
**Fix:** Use `dumpcap -i ... -w ...` for all captures. Use `tshark -r ... -q -z ...` only for post-processing.

### Anti-Pattern 2: Post-processing during active capture

**Symptom:** Packet drops in capture data when tshark stat extraction runs simultaneously.
**Fix:** Post-processing starts only after capture subprocess has exited and file is closed.

### Anti-Pattern 3: Running all tshark queries in parallel

**Symptom:** 5 tshark processes each reading 100 MB = 500 MB disk I/O competing for SD bandwidth. Peak RAM: 5 x 100 MB = 500 MB.
**Fix:** Run queries sequentially with `asyncio.Lock`. Pre-warm page cache. Total time is roughly the same (sequential reads from cache vs parallel reads thrashing SD).

### Anti-Pattern 4: Merging first, then processing the monolith

**Symptom:** 200 MB merged file causes tshark to use 400 MB RSS.
**Fix for large captures:** Process stats per-segment, merge numerical results in Python. Only merge pcap for download/export. (Phase 2 optimization — for MVP, merge-then-process is acceptable up to 100 MB.)

### Anti-Pattern 5: Compressing pcap during capture

**Symptom:** CPU contention between compression and packet capture. Dropped packets.
**Fix:** Never compress during capture. Compress only after all post-processing is complete, if at all.

### Anti-Pattern 6: Sending raw tshark text to AI

**Symptom:** Unpredictable input size (could be 100 KB+), expensive per-call cost, AI misparses tabular text.
**Fix:** Always send structured CaptureSummary JSON. Fixed, predictable, parseable, cheap.

### Anti-Pattern 7: No retention policy ("we'll clean up later")

**Symptom:** SD card fills up after 2 weeks of use. System degrades. User calls it broken.
**Fix:** Auto-retention enforced after every capture completion. 20 captures / 500 MB / 7 days.

### Anti-Pattern 8: Using Python to parse pcap files

**Symptom:** `scapy` or `pyshark` loading a 100 MB pcap into Python objects — 1 GB+ RAM, minutes of processing.
**Fix:** tshark subprocesses for all pcap analysis. Python only parses tshark's text/field output.

### Anti-Pattern 9: Polling file size with stat() in a tight loop

**Symptom:** `os.stat()` every 100ms generates metadata I/O that interferes with capture writes on SD.
**Fix:** Poll at 1-second intervals. File size accuracy to the second is sufficient for UI progress.

### Anti-Pattern 10: Fire-and-forget subprocesses

**Symptom:** Zombie tshark/dumpcap processes after backend restart. PID file stale. Capture marked "running" forever.
**Fix:** Track all subprocess handles. On startup, reconcile state. On shutdown, SIGTERM → wait → SIGKILL.

### Anti-Pattern 11: Ignoring thermal throttling

**Symptom:** Post-processing takes 60s instead of 15s because the CPU throttled to 1.5 GHz.
**Fix:** If capturing and post-processing back-to-back for extended periods, insert a 5-second cooldown between pipeline runs. Monitor `vcgencmd measure_temp` in benchmarks. Require a heatsink for production deployments.

### Anti-Pattern 12: Storing captures on tmpfs/RAM

**Symptom:** Tempting for speed, but a 100 MB capture eats 100 MB RAM. With post-processing overhead, system is at 50%+ RAM for one capture.
**Fix:** Always write to persistent storage. If SD is too slow, use USB 3 SSD.
