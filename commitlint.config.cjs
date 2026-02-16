module.exports = {
  extends: ['@commitlint/config-conventional'],
  ignores: [(message) => message.startsWith('Merge ') || message.startsWith('merge:')],
  rules: {
    'body-max-line-length': [2, 'always', 120],
    'footer-max-line-length': [2, 'always', 120],
  },
}
