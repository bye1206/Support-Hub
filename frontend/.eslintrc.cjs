module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  extends: ["eslint:recommended", "plugin:@typescript-eslint/recommended"],
  parser: "@typescript-eslint/parser",
  plugins: ["@typescript-eslint", "react-hooks", "react-refresh"],
  rules: {
    "react-refresh/only-export-components": "warn",
  },
  ignorePatterns: ["dist", "node_modules", "coverage"],
};
