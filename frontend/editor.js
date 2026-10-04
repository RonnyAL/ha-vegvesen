import { editorConfig, routeSchema } from "./config.js";
import { labels, language } from "./labels.js";

// HA's documented custom-card editor lifecycle, with its native form/selector.
export class VegvesenRouteMapEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._form = document.createElement("ha-form");
    this._form.schema = routeSchema;
    this._form.addEventListener("value-changed", (event) => {
      event.stopPropagation();
      // Migrate legacy entity selections only through the normal editor event.
      // Clearing the device must not restore the old entity selection.
      const config = { ...this._config, ...event.detail.value };
      delete config.entity;
      this.dispatchEvent(
        new CustomEvent("config-changed", {
          detail: { config },
          bubbles: true,
          composed: true,
        }),
      );
    });
    this.shadowRoot.append(this._form);
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
    const label = labels[language(this._hass)].route;
    this._form.computeLabel = () => label;
  }
}

if (!customElements.get("vegvesen-route-map-editor"))
  customElements.define("vegvesen-route-map-editor", VegvesenRouteMapEditor);
