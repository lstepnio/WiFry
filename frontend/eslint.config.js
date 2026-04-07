import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      // Ban browser-native confirm() and alert() to prevent inconsistent UX.
      // Use useConfirm() for confirmations and useNotification().notify() for alerts.
      'no-restricted-globals': ['error',
        { name: 'alert', message: 'Use useNotification().notify() instead of alert() for consistent UX.' },
        { name: 'confirm', message: 'Use useConfirm() instead of confirm() for consistent styled dialogs.' },
      ],
    },
  },
])
