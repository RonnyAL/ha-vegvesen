import test from "node:test";
import assert from "node:assert/strict";
import {
  ForecastData,
  forecastHours,
  forecastLabel,
  HOUR,
} from "./forecast.js";

const NOW = Date.parse("2026-10-06T10:15:00Z");
const flush = () => new Promise((resolve) => setImmediate(resolve));
const setup = async (t) => {
  t.mock.timers.enable({ apis: ["Date", "setTimeout"], now: NOW });
  const frames = [],
    errors = [],
    requests = [],
    pending = [];
  let listener,
    removals = 0;
  const data = new ForecastData(
    (value) => frames.push(value),
    (error) => errors.push(error),
    () => frames.push(null),
  );
  const hass = {
    connected: true,
    connection: {
      subscribeMessage: async (callback) => {
        listener = callback;
        return () => removals++;
      },
    },
    callWS: (message) => {
      requests.push(message);
      return new Promise((resolve, reject) =>
        pending.push({ resolve, reject }),
      );
    },
  };
  const config = { device_id: "route" };
  await data.update(hass, config);
  t.after(() => data.stop());
  return {
    data,
    hass,
    config,
    frames,
    errors,
    requests,
    pending,
    event: (value) => listener(value),
    removals: () => removals,
  };
};

test("default stays on the subscription; hour browsing preserves live updates for returning", async (t) => {
  const { data, frames, requests, pending, event } = await setup(t);
  event({ data: { forecast_time: "live", segments: [1] } });
  assert.equal(requests.length, 0);
  const hour = forecastHours()[2];
  data.select(hour);
  assert.equal(frames.at(-1), null);
  t.mock.timers.tick(200);
  assert.deepEqual(requests[0], {
    type: "vegvesen/route_map",
    device_id: "route",
    forecast_time: hour,
  });
  pending[0].resolve({ forecast_time: hour, segments: [2] });
  await flush();
  event({ data: { forecast_time: "new live", segments: [3] } });
  assert.equal(frames.at(-1).forecast_time, hour);
  assert.equal(requests.length, 1);
  data.select("");
  assert.equal(frames.at(-1).forecast_time, "new live");
  t.mock.timers.tick(300000);
  assert.equal(requests.length, 1);
});

test("rapid taps request only the last queued hour and discard obsolete results", async (t) => {
  const { data, frames, requests, pending } = await setup(t);
  const hours = forecastHours();
  for (const time of hours.slice(1, 4)) data.select(time);
  t.mock.timers.tick(200);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].forecast_time, hours[3]);
  for (const time of hours.slice(4, 7)) data.select(time);
  t.mock.timers.tick(200);
  assert.equal(requests.length, 1);
  pending[0].resolve({ forecast_time: hours[3] });
  await flush();
  assert.equal(frames.at(-1), null);
  t.mock.timers.tick(1);
  assert.equal(requests[1].forecast_time, hours[6]);
  pending[1].resolve({ forecast_time: hours[6] });
  await flush();
  assert.equal(frames.at(-1).forecast_time, hours[6]);
});

test("selected forecasts refresh while visible, pause when hidden and expire explicitly", async (t) => {
  const { data, frames, errors, requests, pending } = await setup(t);
  data.select(forecastHours()[0]);
  t.mock.timers.tick(200);
  pending[0].resolve({ segments: [1] });
  await flush();
  t.mock.timers.tick(300000);
  assert.equal(requests.length, 2);
  pending[1].resolve({ segments: [2] });
  await flush();
  data.setVisible(false);
  t.mock.timers.tick(300000);
  assert.equal(requests.length, 2);
  data.setVisible(true);
  assert.equal(requests.length, 3);
  pending[2].resolve({ segments: [3] });
  await flush();
  // Crossing the containing hour invalidates this fixed choice, not the route.
  t.mock.timers.tick(HOUR);
  assert.equal(frames.at(-1), null);
  assert.equal(errors.at(-1), "forecast_time_out_of_range");
  assert.equal(requests.length, 3);
});

test("failed and empty hours remain distinct, recover, and never become the normal forecast", async (t) => {
  const { data, frames, errors, pending, event } = await setup(t);
  event({ data: { segments: ["normal"] } });
  data.select(forecastHours()[1]);
  t.mock.timers.tick(200);
  pending[0].reject({ code: "forecast_request_failed" });
  await flush();
  assert.equal(frames.at(-1), null);
  assert.equal(errors.at(-1), "forecast_request_failed");
  data.retry();
  pending[1].resolve({ segments: [] });
  await flush();
  assert.deepEqual(frames.at(-1), { segments: [] });
  data.select("");
  assert.deepEqual(frames.at(-1), { segments: ["normal"] });
});

test("disconnect, permission loss and removal reject late responses and release timers", async (t) => {
  const {
    data,
    hass,
    config,
    frames,
    errors,
    requests,
    pending,
    event,
    removals,
  } = await setup(t);
  data.select(forecastHours()[1]);
  t.mock.timers.tick(200);
  event({ error: "unauthorized" });
  pending[0].resolve({ segments: ["private"] });
  await flush();
  assert.equal(frames.at(-1), null);
  assert.equal(errors.at(-1), "unauthorized");
  t.mock.timers.tick(300000);
  assert.equal(requests.length, 1);
  await data.update({ ...hass, connected: false }, config);
  assert.equal(errors.at(-1), "disconnected");
  await data.update(hass, config);
  event({ data: { segments: ["normal"] } });
  assert.equal(requests.length, 2);
  data.stop(true);
  pending[1].resolve({ segments: ["late"] });
  await flush();
  assert.equal(frames.at(-1), null);
  t.mock.timers.tick(300000);
  assert.equal(requests.length, 2);
  assert.equal(removals(), 2);
  assert.equal(data.time, undefined);
});

test("hours cross midnight in UTC and repeated local DST hours have distinct labels", () => {
  const hours = forecastHours(Date.parse("2026-10-24T23:45:00Z"));
  assert.equal(hours.length, 25);
  assert.equal(hours[0], "2026-10-24T23:00:00.000Z");
  assert.equal(hours[24], "2026-10-25T23:00:00.000Z");
  const first = forecastLabel(hours[1], "nb", "Europe/Oslo");
  const second = forecastLabel(hours[2], "nb", "Europe/Oslo");
  assert.match(first, /02:00/);
  assert.match(second, /02:00/);
  assert.notEqual(first, second);
});

test("card default offsets roll at the UTC hour; manual browsing stays absolute", async (t) => {
  const { data, hass, config, requests, pending, event } = await setup(t);
  event({ data: { forecast_time: forecastHours()[5], segments: ["route"] } });
  await data.update(hass, { ...config, default_forecast: "2" });
  t.mock.timers.tick(200);
  assert.equal(requests[0].forecast_time, forecastHours()[2]);
  assert.equal(data.followingDefault, true);
  pending[0].resolve({ forecast_time: data.time, segments: ["card"] });
  await flush();
  // The refresh immediately before rollover schedules the boundary, not five
  // minutes after it. Returning to a default remains relative to the current hour.
  t.mock.timers.setTime(Date.parse("2026-10-06T10:59:59Z"));
  data.refresh(true);
  pending[1].resolve({ forecast_time: data.time, segments: ["card"] });
  await flush();
  t.mock.timers.tick(1000);
  t.mock.timers.tick(200);
  assert.equal(requests[2].forecast_time, "2026-10-06T13:00:00.000Z");
  pending[2].resolve({ forecast_time: data.time, segments: ["rolled"] });
  await flush();
  data.select(forecastHours()[4]);
  const fixed = data.time;
  t.mock.timers.tick(200);
  pending[3].resolve({ forecast_time: fixed, segments: ["manual"] });
  await flush();
  t.mock.timers.setTime(Date.parse("2026-10-06T12:00:00Z"));
  data.refresh(true);
  assert.equal(data.followingDefault, false);
  assert.equal(requests[4].forecast_time, fixed);
  pending[4].resolve({ forecast_time: fixed, segments: ["manual"] });
  await flush();
  data.select();
  t.mock.timers.tick(200);
  assert.equal(requests[5].forecast_time, "2026-10-06T14:00:00.000Z");
});

test("Now default survives hiding and reconnecting; changing default returns to route data", async (t) => {
  const { data, hass, config, pending, requests, frames, event } =
    await setup(t);
  const own = { ...config, default_forecast: "0" };
  event({ data: { forecast_time: forecastHours()[4], segments: ["route"] } });
  await data.update(hass, own);
  t.mock.timers.tick(200);
  assert.equal(requests[0].forecast_time, forecastHours()[0]);
  pending[0].resolve({ segments: ["now"] });
  await flush();
  data.setVisible(false);
  t.mock.timers.tick(HOUR);
  assert.equal(requests.length, 1);
  data.setVisible(true);
  t.mock.timers.tick(200);
  assert.equal(requests[1].forecast_time, forecastHours()[0]);
  pending[1].resolve({ segments: ["new hour"] });
  await flush();
  await data.update({ ...hass, connected: false }, own);
  await data.update(hass, own);
  event({ data: { forecast_time: forecastHours()[4], segments: ["route"] } });
  assert.equal(requests[2].forecast_time, forecastHours()[0]);
  await data.update(hass, config);
  assert.equal(data.time, undefined);
  assert.equal(data.followingDefault, true);
  assert.deepEqual(frames.at(-1).segments, ["route"]);
  pending[2].resolve({ segments: ["late"] });
  await flush();
  assert.deepEqual(frames.at(-1).segments, ["route"]);
  data.stop(true);
  await data.update(hass, own);
  event({
    data: { forecast_time: forecastHours()[4], segments: ["new route"] },
  });
  t.mock.timers.tick(200);
  assert.equal(requests[3].forecast_time, forecastHours()[0]);
});

test("compact labels use Now only for the current UTC hour and retain DST disambiguation", (t) => {
  t.mock.timers.enable({ apis: ["Date"], now: NOW });
  assert.equal(
    forecastLabel(forecastHours()[0], "nb", "Europe/Oslo", true),
    "Nå",
  );
  assert.equal(
    forecastLabel(forecastHours()[0], "en", "Europe/Oslo", true),
    "Now",
  );
  assert.notEqual(
    forecastLabel(forecastHours()[1], "nb", "Europe/Oslo", true),
    "Nå",
  );
  t.mock.timers.setTime(Date.parse("2026-10-24T22:00:00Z"));
  const first = forecastLabel(
    "2026-10-25T00:00:00Z",
    "nb",
    "Europe/Oslo",
    true,
  );
  const second = forecastLabel(
    "2026-10-25T01:00:00Z",
    "nb",
    "Europe/Oslo",
    true,
  );
  assert.notEqual(first, second);
});

test("default-hour responses crossing rollover are discarded and refresh the new hour", async (t) => {
  const { data, hass, config, requests, pending, frames } = await setup(t);
  await data.update(hass, { ...config, default_forecast: "0" });
  t.mock.timers.tick(200);
  t.mock.timers.setTime(Date.parse("2026-10-06T11:00:00Z"));
  pending[0].resolve({ segments: ["old hour"] });
  await flush();
  assert.equal(frames.at(-1), null);
  t.mock.timers.tick(1);
  assert.equal(requests[1].forecast_time, forecastHours()[0]);
  t.mock.timers.setTime(Date.parse("2026-10-06T12:00:00Z"));
  pending[1].reject({ code: "forecast_time_out_of_range" });
  await flush();
  t.mock.timers.tick(1);
  assert.equal(requests[2].forecast_time, forecastHours()[0]);
  data.stop();
  pending[2].resolve({ segments: ["detached"] });
  await flush();
  // No overwritten debounce timer survives a late old-hour response or detach.
  t.mock.timers.tick(HOUR);
  assert.equal(requests.length, 3);
  assert.equal(frames.at(-1), null);
});

test("changing a card default while disconnected retains the connection error", async (t) => {
  const { data, hass, config, errors, requests, event } = await setup(t);
  await data.update(
    { ...hass, connected: false },
    { ...config, default_forecast: "0" },
  );
  assert.equal(errors.at(-1), "disconnected");
  t.mock.timers.tick(200);
  assert.equal(requests.length, 0);
  await data.update(hass, { ...config, default_forecast: "0" });
  event({ data: { forecast_time: forecastHours()[2], segments: [] } });
  assert.equal(requests[0].forecast_time, forecastHours()[0]);
});
