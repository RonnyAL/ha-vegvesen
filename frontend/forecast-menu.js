// A card-contained menu: no OS picker or dependency on HA's changing menu
// components. Follow the WAI-ARIA menu-button/radio-item keyboard pattern.
export class ForecastMenu {
  constructor(trigger, prepare, select) {
    this.trigger = trigger;
    this.prepare = prepare;
    this.select = select;
    this.element = document.createElement("div");
    this.element.className = "forecast-menu";
    this.element.id = "forecast-hours";
    this.element.hidden = true;
    this.element.setAttribute("role", "menu");
    trigger.setAttribute("aria-controls", this.element.id);
    trigger.setAttribute("aria-haspopup", "menu");
    trigger.setAttribute("aria-expanded", "false");
    trigger.onclick = () => {
      if (this.element.hidden) this.open();
      else this.close(true);
    };
    trigger.onkeydown = (event) => {
      if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
      event.preventDefault();
      this.open(event.key === "ArrowUp" ? -1 : 0);
    };
    this.element.onkeydown = (event) => this.keydown(event);
  }

  update(choices, value, label) {
    this.element.setAttribute("aria-label", label);
    // Subscription updates must not reset scrolling or keyboard focus.
    const key = JSON.stringify(choices);
    if (key !== this.key) {
      const focused = this.element.getRootNode().activeElement?.dataset?.value;
      const scroll = this.list?.scrollTop ?? 0;
      this.list = document.createElement("div");
      this.list.className = "forecast-menu-hours";
      this.list.setAttribute("role", "presentation");
      this.items = choices.map((choice) => {
        const item = document.createElement("button");
        item.type = "button";
        item.tabIndex = -1;
        item.dataset.value = choice.value;
        item.setAttribute("role", "menuitemradio");
        item.setAttribute("aria-label", choice.accessibleLabel ?? choice.label);
        const check = document.createElement("ha-icon");
        check.setAttribute("icon", "mdi:check");
        check.setAttribute("aria-hidden", "true");
        const text = document.createElement("span");
        text.textContent = choice.label;
        item.append(check, text);
        if (choice.hint) {
          const hint = document.createElement("small");
          hint.textContent = choice.hint;
          item.append(hint);
        }
        item.onclick = () => {
          this.close(true);
          this.select(choice.value);
        };
        return item;
      });
      let day;
      for (let i = 1; i < choices.length; i++) {
        if (choices[i].day !== day) {
          day = choices[i].day;
          const heading = document.createElement("div");
          heading.className = "forecast-menu-day";
          heading.textContent = day;
          heading.setAttribute("aria-hidden", "true");
          this.list.append(heading);
        }
        this.list.append(this.items[i]);
      }
      this.element.replaceChildren(this.items[0], this.list);
      this.list.scrollTop = scroll;
      if (focused && !this.element.hidden)
        this.focus(
          this.items.find((item) => item.dataset.value === focused) ??
            this.items[0],
        );
      this.key = key;
    }
    for (const item of this.items)
      item.setAttribute("aria-checked", String(item.dataset.value === value));
  }

  open(index) {
    this.prepare();
    this.close();
    this.element.hidden = false;
    this.trigger.setAttribute("aria-expanded", "true");
    const item =
      index === undefined
        ? this.items.find(
            (item) => item.getAttribute("aria-checked") === "true",
          )
        : this.items.at(index);
    this.focus(item ?? this.items[0]);
    this.listeners = new AbortController();
    const outside = (event) => {
      const path = event.composedPath();
      if (!path.includes(this.element) && !path.includes(this.trigger))
        this.close();
    };
    for (const type of ["pointerdown", "focusin"])
      document.addEventListener(type, outside, {
        capture: true,
        signal: this.listeners.signal,
      });
  }

  close(restoreFocus = false) {
    this.listeners?.abort();
    this.listeners = undefined;
    this.element.hidden = true;
    this.trigger.setAttribute("aria-expanded", "false");
    this.search = "";
    if (restoreFocus) this.trigger.focus({ preventScroll: true });
  }

  focus(item) {
    item.focus({ preventScroll: true });
    // Scroll only the menu, never the dashboard (including in fullscreen).
    if (item.parentNode !== this.list) return;
    const row = item.getBoundingClientRect();
    const list = this.list.getBoundingClientRect();
    if (row.top < list.top) this.list.scrollTop += row.top - list.top;
    else if (row.bottom > list.bottom)
      this.list.scrollTop += row.bottom - list.bottom;
  }

  keydown(event) {
    const index = this.items.indexOf(event.target);
    if (event.key === "Escape" || event.key === "Tab") {
      // Return to the trigger before Tab's native navigation out of the menu.
      this.close(true);
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
      }
      return;
    }
    let next;
    if (event.key === "ArrowDown") next = (index + 1) % this.items.length;
    if (event.key === "ArrowUp")
      next = (index - 1 + this.items.length) % this.items.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = this.items.length - 1;
    if (next !== undefined) {
      event.preventDefault();
      this.focus(this.items[next]);
    } else if (
      event.key.length === 1 &&
      event.key !== " " &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey
    ) {
      event.preventDefault();
      const now = Date.now();
      this.search =
        (now - this.searchTime < 700 ? this.search : "") +
        event.key.toLocaleLowerCase();
      this.searchTime = now;
      const items = [
        ...this.items.slice(index + 1),
        ...this.items.slice(0, index + 1),
      ];
      const match = items.find((item) =>
        item.textContent.toLocaleLowerCase().startsWith(this.search),
      );
      if (match) this.focus(match);
    }
    // Native buttons activate with Enter or Space; navigation alone never queries.
  }
}
