import tseslint from "typescript-eslint";
export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**"] },
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            "../../app/*",
            "../../lib/*",
            "../../components/*",
            "../../research/*",
            "../../backend/*",
          ],
        },
      ],
    },
  },
);
