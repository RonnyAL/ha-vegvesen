import js from "@eslint/js";

export default [
  js.configs.recommended,
  {
    files: ["custom_components/vegvesen/frontend/*.js", "tests/frontend/*.js"],
    languageOptions: {
      globals: {
        HTMLElement: "readonly",
        customElements: "readonly",
        CustomEvent: "readonly",
        Option: "readonly",
        queueMicrotask: "readonly",
      },
    },
  },
];
