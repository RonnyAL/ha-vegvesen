import * as maplibregl from "maplibre-gl";
import { sourceGroups } from "./source-groups.js";
import { sourceSections } from "./sources.js";

export const element = (tag, className, text) => {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  if (tag === "button") item.type = "button";
  return item;
};
export const icon = (name) => {
  const item = element("ha-icon");
  item.setAttribute("icon", name);
  item.setAttribute("aria-hidden", "true");
  return item;
};

// Native buttons keep their click/keyboard behavior, but their gestures must
// not also reach the map's pan, double-tap zoom or keyboard handlers.
const isolateControl = (control) => {
  for (const event of [
    "mousedown",
    "mouseup",
    "touchstart",
    "touchmove",
    "touchend",
    "dblclick",
    "wheel",
    "keydown",
    "keyup",
  ])
    control.addEventListener(event, (event) => event.stopPropagation(), {
      passive: true,
    });
  return control;
};

// A small presentation layer shared by physical source types. It owns neither
// HA entities nor discovery. Use public MapLibre markers/events and a bounded
// in-map list, like the card's other detail panels, with native button semantics.
export class SourceMarkers {
  constructor(frame, onSelect, onExpand) {
    Object.assign(this, { frame, onSelect, onExpand });
    this.markers = new Map();
    this.regroup = () => this.draw();
    this.dismiss = () => this.collapse();
  }

  update(items, map, labels) {
    if (map !== this.map) {
      this.remove();
      this.map = map;
      map?.on("zoomend", this.regroup);
      map?.on("resize", this.regroup);
      map?.on("movestart", this.dismiss);
      map?.on("click", this.dismiss);
    }
    Object.assign(this, { items, labels });
    if (!map) return;
    this.draw();
  }

  draw() {
    const map = this.map;
    if (!map) return;
    this.groups = sourceGroups(this.items, (point) => map.project(point));
    const groupIds = new Set(this.groups.map((group) => group.id));
    if (!groupIds.has(this.expanded)) this.collapse();
    for (const [id, marker] of this.markers) {
      if (!groupIds.has(id)) {
        marker.remove();
        this.markers.delete(id);
      }
    }
    for (const group of this.groups) {
      let marker = this.markers.get(group.id);
      if (!marker) {
        marker = new maplibregl.Marker({
          element: isolateControl(element("button", "source-marker")),
        })
          .setLngLat(map.unproject(group.center))
          .addTo(map);
        this.markers.set(group.id, marker);
      }
      marker.setLngLat(map.unproject(group.center));
      const button = marker.getElement();
      const multiple = group.items.length > 1;
      const sections = sourceSections(group.items, this.labels);
      const name = multiple
        ? sections.map((section) => section.label).join(", ")
        : group.items[0].name;
      button.title = name;
      button.setAttribute("aria-label", name);
      button.classList.toggle("source-cluster", multiple);
      if (multiple)
        button.setAttribute(
          "aria-expanded",
          String(this.expanded === group.id),
        );
      else button.removeAttribute("aria-expanded");
      // Keep the focusable button itself in place while source metadata updates.
      const symbols = element("span", "source-symbols");
      symbols.classList.toggle("source-mixed", sections.length > 1);
      symbols.append(...sections.map((section) => icon(section.icon)));
      button.replaceChildren(symbols);
      if (multiple)
        button.append(
          element("span", "source-count", String(group.items.length)),
        );
      button.onclick = (event) => {
        event.stopPropagation();
        if (multiple) this.expand(group.id, event.detail === 0);
        else {
          this.collapse();
          this.origin = button;
          this.selected = group.items[0].id;
          this.onSelect(group.items[0], event.detail === 0);
        }
      };
    }
    this.renderBubble();
  }

  expand(id, focus) {
    if (this.expanded === id) {
      this.collapse(true);
      return;
    }
    this.collapse();
    this.onExpand();
    this.expanded = id;
    this.origin = this.markers.get(id)?.getElement();
    this.origin?.setAttribute("aria-expanded", "true");
    this.renderBubble();
    if (focus)
      this.bubble
        ?.querySelector(".source-choice")
        ?.focus({ preventScroll: true });
  }

  renderBubble() {
    const group = this.groups?.find((g) => g.id === this.expanded);
    if (!group || this.held) return;
    if (!this.bubble) {
      this.bubble = isolateControl(
        element("section", "source-bubble source-picker"),
      );
      this.bubble.onclick = (event) => event.stopPropagation();
      this.bubble.onkeydown = (event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          this.collapse(true);
        }
      };
      this.bubble.onpointerenter = this.bubble.onfocusin = () =>
        this.cancelCollapse();
      this.bubble.onpointerleave = this.bubble.onfocusout = () => {
        if (this.returned) this.scheduleCollapse();
      };
      this.frame.append(this.bubble);
    }
    const sections = sourceSections(group.items, this.labels);
    const title =
      sections.length === 1
        ? sections[0].label
        : this.labels.source_group.replace("{count}", group.items.length);
    this.bubble.setAttribute("aria-label", title);
    let heading = this.bubble.querySelector(".panel-heading");
    let choices = this.bubble.querySelector(".source-choices");
    if (!heading) {
      heading = element("div", "panel-heading");
      const close = element("button", "panel-close");
      close.append(icon("mdi:close"));
      close.onclick = () => this.collapse(true);
      heading.append(element("h3"), close);
      choices = element("div", "source-choices");
      this.bubble.append(heading, choices);
    }
    heading.querySelector("h3").textContent = title;
    heading
      .querySelector("button")
      .setAttribute("aria-label", this.labels.collapse_sources);
    const buttons = new Map(
      [...choices.querySelectorAll(".source-choice")].map((button) => [
        button.dataset.sourceId,
        button,
      ]),
    );
    const ids = new Set(group.items.map((item) => item.id));
    for (const [id, button] of buttons) if (!ids.has(id)) button.remove();
    for (const section of [...choices.children])
      if (!sections.some((item) => item.kind === section.dataset.kind))
        section.remove();
    sections.forEach((data, sectionIndex) => {
      let section = [...choices.children].find(
        (item) => item.dataset.kind === data.kind,
      );
      if (!section) {
        section = element("section", "source-section");
        section.dataset.kind = data.kind;
        section.append(element("h4"), element("ul", "source-list"));
      }
      section.setAttribute("aria-label", data.label);
      section.querySelector("h4").textContent = data.label;
      section.querySelector("h4").hidden = sections.length === 1;
      const list = section.querySelector("ul");
      for (const row of [...list.children])
        if (!row.firstElementChild) row.remove();
      data.items.forEach((item, index) => {
        let button = buttons.get(item.id);
        if (!button) {
          button = element("button", "source-choice");
          button.dataset.sourceId = item.id;
          const copy = element("span", "source-choice-copy");
          copy.append(
            element("span", "source-choice-name"),
            element("span", "source-choice-detail"),
          );
          button.append(icon(item.icon), copy);
          element("li").append(button);
        }
        button.querySelector("ha-icon").setAttribute("icon", item.icon);
        button.querySelector(".source-choice-name").textContent = item.heading;
        button.querySelector(".source-choice-detail").textContent = item.detail;
        button.onclick = (event) => {
          this.selected = item.id;
          this.hold();
          this.onSelect(item, event.detail === 0);
        };
        // Preserve buttons through unrelated HA updates, including an in-progress
        // tap or keyboard interaction. Do not detach/reinsert an unchanged node.
        const row = button.parentElement;
        if (list.children[index] !== row)
          list.insertBefore(row, list.children[index] ?? null);
      });
      if (choices.children[sectionIndex] !== section)
        choices.insertBefore(section, choices.children[sectionIndex] ?? null);
    });
  }

  hold() {
    this.cancelCollapse();
    this.held = true;
    this.bubble?.remove();
    this.bubble = undefined;
  }

  release(focus = false) {
    this.held = false;
    this.returned = true;
    this.renderBubble();
    const group = this.groups?.find((g) =>
      g.items.some((item) => item.id === this.selected),
    );
    this.origin = this.markers.get(group?.id)?.getElement();
    const choice = [
      ...(this.bubble?.querySelectorAll(".source-choice") ?? []),
    ].find((button) => button.dataset.sourceId === this.selected);
    (focus ? (choice ?? this.origin) : this.origin)?.focus({
      preventScroll: true,
    });
    this.scheduleCollapse();
  }

  scheduleCollapse() {
    this.cancelCollapse();
    if (!this.expanded || this.held) return;
    this.collapseTimer = setTimeout(() => {
      this.collapseTimer = undefined;
      const active = this.bubble?.getRootNode().activeElement;
      if (
        this.bubble?.matches(":hover") ||
        (active && this.bubble?.contains(active))
      )
        return;
      this.collapse();
    }, 8000);
  }

  cancelCollapse() {
    clearTimeout(this.collapseTimer);
    this.collapseTimer = undefined;
  }

  collapse(focus = false) {
    this.cancelCollapse();
    this.bubble?.remove();
    this.bubble = undefined;
    this.markers
      .get(this.expanded)
      ?.getElement()
      .setAttribute("aria-expanded", "false");
    this.expanded = undefined;
    this.held = this.returned = false;
    if (focus) this.origin?.focus({ preventScroll: true });
  }

  remove() {
    this.collapse();
    this.map?.off("zoomend", this.regroup);
    this.map?.off("resize", this.regroup);
    this.map?.off("movestart", this.dismiss);
    this.map?.off("click", this.dismiss);
    this.markers.forEach((marker) => marker.remove());
    this.markers.clear();
    this.map = undefined;
  }
}
