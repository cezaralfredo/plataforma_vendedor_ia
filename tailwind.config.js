module.exports = {
  content: ['./app/admin/templates/**/*.html', './app/admin/static/**/*.js'],
  safelist: [{ pattern: /^(status|payment)-/ }],
  theme: { extend: {} },
  plugins: [],
};
