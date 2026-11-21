module.exports = {
  content: [
    './app/admin/templates/**/*.html',
    './app/admin/static/**/*.js',
    './app/seller/templates/**/*.html',
  ],
  safelist: [{ pattern: /^(status|payment)-/ }],
  theme: { extend: {} },
  plugins: [],
};
