import { RouteData, routeTarget } from "./data.js";

export const HOUR = 3600000;
const REFRESH = 5 * 60000;
export const forecastHours = (now = Date.now()) => {
  const start = Math.floor(now / HOUR) * HOUR;
  // Same request limit as get_route_forecasts; availability is not guaranteed.
  return Array.from({ length: 25 }, (_, i) =>
    new Date(start + i * HOUR).toISOString(),
  );
};
export const forecastLabel = (value, language, timeZone) => {
  const options = {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  };
  const format = new Intl.DateTimeFormat(language, options);
  const time = Date.parse(value);
  const label = format.format(time);
  // Show offsets only for repeated local hours; ordinary labels fit on mobile.
  return [-HOUR, HOUR].some((offset) => format.format(time + offset) === label)
    ? new Intl.DateTimeFormat(language, {
        ...options,
        timeZoneName: "shortOffset",
      }).format(time)
    : label;
};

// The default remains the coordinator subscription. An explicitly selected hour
// is local to this card, using the same server cache as automation actions.
export class ForecastData {
  constructor(onData, onError, onReset) {
    Object.assign(this, { onData, onError, onReset });
    this.visible = true;
    this.revision = 0;
    this.base = new RouteData(
      (data) => {
        this.live = data;
        this.liveError = undefined;
        if (this.time) this.refresh();
        else this.onData(data);
      },
      (error) => {
        this.liveError = error;
        this.onError(error);
        // A failed configured-hour poll need not prevent another hour working.
        // Every explicit request rechecks route identity and read permissions.
        if (this.time && error === "unavailable") this.refresh(true);
      },
      () => {
        this.live = undefined;
        this.cancel();
        this.onReset();
      },
    );
  }

  cancel() {
    this.revision++;
    clearTimeout(this.timer);
    this.timer = undefined;
    this.pending = undefined;
    this.fetched = 0;
  }

  stop(resetTime = false) {
    this.cancel();
    this.base.stop();
    this.live = undefined;
    if (resetTime) this.time = undefined;
  }

  update(hass, config) {
    Object.assign(this, { hass, config });
    return this.base.update(hass, config);
  }

  select(time) {
    this.time = time || undefined;
    this.revision++;
    this.fetched = 0;
    clearTimeout(this.timer);
    this.onReset();
    if (!this.time) {
      if (this.live) this.onData(this.live);
      else this.onError(this.liveError ?? "loading");
    } else {
      this.onError("forecast_loading");
      // Coalesce quick arrow taps; an in-flight query queues only the last choice.
      this.timer = setTimeout(() => this.refresh(), 200);
    }
  }

  setVisible(visible) {
    if (this.visible === visible) return;
    this.visible = visible;
    clearTimeout(this.timer);
    if (visible) this.refresh(true);
  }

  retry() {
    if (this.time) this.refresh(true);
    else {
      this.base.stop();
      this.update(this.hass, this.config);
    }
  }

  async refresh(force = false) {
    if (!this.time || !this.visible || !this.hass?.connected || this.pending)
      return;
    const time = this.time;
    if (!forecastHours().includes(time)) {
      this.onReset();
      this.onError("forecast_time_out_of_range");
      return;
    }
    if (!force && Date.now() - this.fetched < REFRESH) return;
    clearTimeout(this.timer);
    const request = { time, revision: this.revision };
    this.pending = request;
    let retryable = true;
    try {
      const data = await this.hass.callWS({
        type: "vegvesen/route_map",
        ...routeTarget(this.config),
        forecast_time: time,
      });
      if (
        this.pending !== request ||
        request.revision !== this.revision ||
        !this.visible
      )
        return;
      this.fetched = Date.now();
      this.onData(data);
    } catch (error) {
      if (
        this.pending !== request ||
        request.revision !== this.revision ||
        !this.visible
      )
        return;
      retryable = ![
        "unauthorized",
        "invalid_route",
        "unknown_command",
        "forecast_time_out_of_range",
      ].includes(error.code);
      if (!retryable) this.live = undefined;
      this.onReset();
      this.onError(
        error.code === "unknown_command"
          ? "upgrade"
          : (error.code ?? "unavailable"),
      );
    } finally {
      if (this.pending === request) {
        this.pending = undefined;
        if (this.time && this.visible && retryable) {
          const delay =
            request.revision !== this.revision
              ? 0
              : Math.min(
                  REFRESH,
                  Math.max(20, Date.parse(this.time) + HOUR - Date.now()),
                );
          this.timer = setTimeout(() => this.refresh(true), delay);
        }
      }
    }
  }
}
