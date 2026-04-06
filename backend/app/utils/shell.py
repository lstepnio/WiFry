"""Safe async subprocess wrapper for system commands."""

import asyncio
import logging
import shlex
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


async def run(
    *args: str,
    sudo: bool = False,
    timeout: float = 30.0,
    check: bool = False,
) -> CommandResult:
    """Run a command asynchronously and return its output.

    Args:
        *args: Command and arguments (e.g., "tc", "qdisc", "show").
        sudo: Prepend "sudo" to the command.
        timeout: Maximum seconds to wait.
        check: Raise on non-zero exit code.

    Returns:
        CommandResult with returncode, stdout, stderr.

    Raises:
        RuntimeError: If check=True and command fails.
        asyncio.TimeoutError: If command exceeds timeout.
    """
    cmd = list(args)
    if sudo:
        cmd = ["sudo", *cmd]

    cmd_str = shlex.join(cmd)
    logger.debug("Running: %s", cmd_str)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise

    result = CommandResult(
        returncode=proc.returncode or 0,
        stdout=stdout_bytes.decode().strip(),
        stderr=stderr_bytes.decode().strip(),
    )

    if result.stderr:
        logger.debug("stderr: %s", result.stderr)

    if check and not result.success:
        raise RuntimeError(
            f"Command failed (exit {result.returncode}): {cmd_str}\n{result.stderr}"
        )

    return result


async def sudo_write(path: str, content: str) -> CommandResult:
    """Write content to a file using sudo tee (for privileged paths).

    Use this instead of Path.write_text() when the running user doesn't
    own the target file (e.g., /etc/hostapd/hostapd.conf).
    """
    logger.debug("sudo_write: %s (%d bytes)", path, len(content))

    proc = await asyncio.create_subprocess_exec(
        "sudo", "tee", path,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=content.encode()), timeout=10.0
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise

    result = CommandResult(
        returncode=proc.returncode or 0,
        stdout=stdout_bytes.decode().strip(),
        stderr=stderr_bytes.decode().strip(),
    )

    if not result.success:
        raise RuntimeError(
            f"sudo_write failed (exit {result.returncode}): {path}\n{result.stderr}"
        )

    return result


class MockShell:
    """Mock shell that logs commands instead of executing them.

    Used for development on non-Linux systems.
    """

    def __init__(self) -> None:
        self.history: list[list[str]] = []

    async def run(
        self,
        *args: str,
        sudo: bool = False,
        timeout: float = 30.0,
        check: bool = False,
    ) -> CommandResult:
        cmd = list(args)
        if sudo:
            cmd = ["sudo", *cmd]

        self.history.append(cmd)
        logger.info("Mock command: %s", shlex.join(cmd))

        return CommandResult(returncode=0, stdout="", stderr="")
