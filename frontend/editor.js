import { changedConfig, editorConfig, routeSchema } from "./config.js";
import { labels, language } from "./labels.js";

// Extra modules can arrive before HA initializes its custom-element registry.
// Wait for its root component before defining either the editor or the card
// (which imports this module). This is ordinary Web Component readiness, not a
// patched registry or a dependency on dashboard internals.
await customElements.whenDefined("home-assistant");

// HA's documented custom-card editor lifecycle, with its native form/selector.
export class VegvesenRouteMapEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._form = document.createElement("ha-form");
    this._form.addEventListener("value-changed", (event) => {
      event.stopPropagation();
      // Migrate legacy entity selections only through the normal editor event.
      // Clearing the device must not restore the old entity selection.
      const config = changedConfig(this._config, event.detail.value);
      this.dispatchEvent(
        new CustomEvent("config-changed", {
          detail: { config },
          bubbles: true,
          composed: true,
        }),
      );
    });
  }

  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._config || !this._hass) return;
    this._form.hass = this._hass;
    this._form.data = editorConfig(this._config, this._hass);
    const lang = language(this._hass);
    if (this._lang !== lang) {
      this._lang = lang;
      const l = labels[lang];
      this._form.schema = routeSchema(l);
      this._form.computeLabel = (schema) => l.editor[schema.name];
    }
    // Native fields require hass during their first connected render. HA can
    // attach an editor before it has supplied both hass and configuration.
    if (!this._form.parentNode) this.shadowRoot.append(this._form);
  }
}

if (!customElements.get("vegvesen-route-map-editor"))
  customElements.define("vegvesen-route-map-editor", VegvesenRouteMapEditor);
