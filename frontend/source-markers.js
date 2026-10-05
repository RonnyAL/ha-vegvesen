import * as maplibregl from "maplibre-gl";
import { sourceGroups } from "./source-groups.js";

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
// HA entities nor discovery. Use public MapLibre Marker/Popup and map events.
export class SourceMarkers {
  constructor(onSelect, onExpand) {
    Object.assign(this, { onSelect, onExpand });
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
      const name = multiple
        ? this.labels.expand_sources.replace("{count}", group.items.length)
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
      const symbols = new Set(group.items.map((item) => item.icon));
      const symbol =
        symbols.size === 1 ? group.items[0].icon : "mdi:map-marker-multiple";
      // Keep the focusable button itself in place while source metadata updates.
      button.replaceChildren(icon(symbol));
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
    if (!this.popup) {
      this.bubble = isolateControl(element("section", "source-bubble"));
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
      this.popup = new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
        focusAfterOpen: false,
        offset: 22,
        className: "source-popup",
      })
        .setLngLat(this.map.unproject(group.center))
        .setDOMContent(this.bubble)
        .addTo(this.map);
    }
    this.popup.setMaxWidth(
      `${Math.min(280, this.map.getContainer().clientWidth - 80)}px`,
    );
    const height = this.map.getContainer().clientHeight;
    const space = Math.max(group.center.y, height - group.center.y);
    this.popup
      .getElement()
      .style.setProperty(
        "--source-popup-max-height",
        `${Math.max(44, Math.min(height - 48, space - 40))}px`,
      );
    const title = this.labels.source_group.replace(
      "{count}",
      group.items.length,
    );
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
      [...choices.children].map((button) => [button.dataset.sourceId, button]),
    );
    const ids = new Set(group.items.map((item) => item.id));
    for (const [id, button] of buttons) if (!ids.has(id)) button.remove();
    group.items.forEach((item, index) => {
      let button = buttons.get(item.id);
      if (!button) {
        button = element("button", "source-choice");
        button.dataset.sourceId = item.id;
        button.append(icon(item.icon), element("span"));
      }
      button.querySelector("ha-icon").setAttribute("icon", item.icon);
      button.querySelector("span").textContent = item.name;
      button.onclick = (event) => {
        this.selected = item.id;
        this.hold();
        this.onSelect(item, event.detail === 0);
      };
      // Preserve buttons through unrelated HA updates, including an in-progress
      // tap or keyboard interaction. Do not detach/reinsert an unchanged node.
      if (choices.children[index] !== button)
        choices.insertBefore(button, choices.children[index] ?? null);
    });
    this.popup.setLngLat(this.map.unproject(group.center));
  }

  hold() {
    this.cancelCollapse();
    this.held = true;
    this.popup?.remove();
    this.popup = this.bubble = undefined;
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
    this.popup?.remove();
    this.popup = this.bubble = undefined;
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
