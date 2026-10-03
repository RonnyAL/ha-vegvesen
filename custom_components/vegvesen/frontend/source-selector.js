/** Dependent source dropdowns. All browsing is local to this form. */

export const UNCLASSIFIED = "__unclassified__";
const areaKey = (name) => name ?? UNCLASSIFIED;
const sorted = (values) =>
  [...new Set(values)].sort((a, b) => a.localeCompare(b));

export class SourceSelection {
  constructor(options = []) {
    this.options = options;
    this.county = "";
    this.municipality = "";
    this.value = "";
  }

  get counties() {
    return sorted(this.options.map((source) => areaKey(source.county)));
  }

  get municipalities() {
    if (!this.county) return [];
    return sorted(
      this.options
        .filter((source) => areaKey(source.county) === this.county)
        .map((source) => areaKey(source.municipality)),
    );
  }

  get sources() {
    if (!this.county || !this.municipality) return [];
    return this.options.filter(
      (source) =>
        areaKey(source.county) === this.county &&
        areaKey(source.municipality) === this.municipality,
    );
  }

  setCounty(county) {
    this.county = this.counties.includes(county) ? county : "";
    this.municipality = "";
    this.value = "";
  }

  setMunicipality(municipality) {
    this.municipality = this.municipalities.includes(municipality)
      ? municipality
      : "";
    this.value = "";
  }

  select(value) {
    this.value = this.sources.some((source) => source.value === value)
      ? value
      : "";
  }

  restore(value) {
    const source = this.options.find((option) => option.value === value);
    if (!source) {
      this.setCounty("");
      return;
    }
    this.county = areaKey(source.county);
    this.municipality = areaKey(source.municipality);
    this.value = source.value;
  }

  replaceOptions(options) {
    this.options = options;
    if (this.value) {
      this.restore(this.value);
    } else if (!this.counties.includes(this.county)) {
      this.setCounty("");
    } else if (!this.municipalities.includes(this.municipality)) {
      this.setMunicipality("");
    }
  }
}

const TEXT = {
  en: {
    county: "County",
    municipality: "Municipality",
    source: "Source",
    chooseCounty: "Choose a county",
    chooseMunicipality: "Choose a municipality",
    chooseSource: "Choose a source",
    unknownCounty: "Unknown county",
    unknownMunicipality: "Unknown municipality",
  },
  nb: {
    county: "Fylke",
    municipality: "Kommune",
    source: "Datakilde",
    chooseCounty: "Velg et fylke",
    chooseMunicipality: "Velg en kommune",
    chooseSource: "Velg en datakilde",
    unknownCounty: "Ukjent fylke",
    unknownMunicipality: "Ukjent kommune",
  },
};

// This guard also lets Node test the selection model without a DOM dependency.
if (globalThis.customElements && globalThis.HTMLElement) {
  class VegvesenSourceSelector extends HTMLElement {
    constructor() {
      super();
      this._selection = new SourceSelection();
      this._disabled = false;
      this._required = true;
      this._queued = false;
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; }
          label { display: block; margin-bottom: 20px; }
          label:last-child { margin-bottom: 0; }
          span { display: block; margin-bottom: 6px; font-size: 14px; }
          select {
            width: 100%; min-height: 48px; padding: 10px 12px;
            box-sizing: border-box; font: inherit; color: var(--primary-text-color);
            background: var(--card-background-color, white);
            border: 1px solid var(--divider-color, #999); border-radius: 6px;
          }
          select:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); }
          select:disabled { color: var(--disabled-text-color, #888); opacity: .65; }
        </style>
        <label><span></span><select id="county"></select></label>
        <label><span></span><select id="municipality"></select></label>
        <label><span></span><select id="source"></select></label>
      `;
      this._county = this.shadowRoot.querySelector("#county");
      this._municipality = this.shadowRoot.querySelector("#municipality");
      this._source = this.shadowRoot.querySelector("#source");
      this._county.addEventListener("change", () => {
        this._selection.setCounty(this._county.value);
        this._changed();
      });
      this._municipality.addEventListener("change", () => {
        this._selection.setMunicipality(this._municipality.value);
        this._changed();
      });
      this._source.addEventListener("change", () => {
        this._selection.select(this._source.value);
        this._changed();
      });

      // HA may create the tag before the asynchronously loaded module arrives.
      // Recover properties assigned to that element before its upgrade.
      for (const key of [
        "hass",
        "label",
        "required",
        "disabled",
        "selector",
        "value",
      ]) {
        if (Object.hasOwn(this, key)) {
          const value = this[key];
          delete this[key];
          this[key] = value;
        }
      }
      this._queueRender();
    }

    set hass(value) {
      this._hass = value;
      this._queueRender();
    }

    set label(value) {
      this._label = value;
      this._queueRender();
    }

    set required(value) {
      this._required = value;
      this._queueRender();
    }

    set disabled(value) {
      this._disabled = value;
      this._queueRender();
    }

    set selector(value) {
      const options = value?.vegvesen_source?.options ?? [];
      if (options !== this._selection.options) {
        this._selection.replaceOptions(options);
      }
      this._queueRender();
    }

    set value(value) {
      if ((value ?? "") !== this._selection.value) {
        this._selection.restore(value);
      }
      this._queueRender();
    }

    get value() {
      return this._selection.value;
    }

    reportValidity() {
      return this._disabled || !this._required || !!this.value;
    }

    focus() {
      const field = !this._selection.county
        ? this._county
        : !this._selection.municipality
          ? this._municipality
          : this._source;
      field.focus();
    }

    _changed() {
      this._render();
      this.dispatchEvent(
        new CustomEvent("value-changed", {
          detail: { value: this.value },
          bubbles: true,
          composed: true,
        }),
      );
    }

    _queueRender() {
      if (this._queued) return;
      this._queued = true;
      queueMicrotask(() => {
        this._queued = false;
        this._render();
      });
    }

    _setOptions(field, placeholder, options, value, disabled) {
      const blank = new Option(placeholder, "");
      field.replaceChildren(
        blank,
        ...options.map((option) => new Option(option.label, option.value)),
      );
      field.value = value;
      field.disabled = this._disabled || disabled;
      field.required = this._required;
    }

    _render() {
      const language = this._hass?.language ?? "en";
      const text = TEXT[language === "nb" || language === "no" ? "nb" : "en"];
      const labels = this.shadowRoot.querySelectorAll("span");
      labels[0].textContent = text.county;
      labels[1].textContent = text.municipality;
      labels[2].textContent = this._label || text.source;
      const selection = this._selection;
      this._setOptions(
        this._county,
        text.chooseCounty,
        selection.counties.map((value) => ({
          value,
          label: value === UNCLASSIFIED ? text.unknownCounty : value,
        })),
        selection.county,
        !selection.options.length,
      );
      this._setOptions(
        this._municipality,
        text.chooseMunicipality,
        selection.municipalities.map((value) => ({
          value,
          label: value === UNCLASSIFIED ? text.unknownMunicipality : value,
        })),
        selection.municipality,
        !selection.county,
      );
      this._setOptions(
        this._source,
        text.chooseSource,
        selection.sources,
        selection.value,
        !selection.municipality,
      );
    }
  }

  if (!customElements.get("ha-selector-vegvesen_source")) {
    customElements.define(
      "ha-selector-vegvesen_source",
      VegvesenSourceSelector,
    );
  }
}
