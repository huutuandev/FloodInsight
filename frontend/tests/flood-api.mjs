import assert from "node:assert/strict";

const gateway = (process.env.FLOOD_TEST_GATEWAY ?? "http://127.0.0.1:8000") + "/api/v1/";
const proxy = (process.env.DASHBOARD_TEST_URL ?? "http://127.0.0.1:3000") + "/api/backend/";
async function json(path, body, base = gateway) {
  const response = await fetch(base + path, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const payload = await response.json();
  assert.ok(response.ok, path + " returned " + response.status + " " + JSON.stringify(payload));
  assert.ok("data" in payload);
  return payload.data;
}

const [points, latest, coverage, metrics, predictions] = await Promise.all([
  json("flood-risk/locations"), json("flood-risk/latest"), json("flood-data/coverage"),
  json("flood-predictions/metrics"), json("flood-predictions/results?current=true"),
]);
assert.ok(points.length > 0);
assert.equal(latest.length, points.length);
assert.ok(points.every((point) => Number.isFinite(point.latitude) && Number.isFinite(point.longitude)));
assert.ok(latest.every((row) => typeof row.is_current === "boolean"));
assert.ok(Number.isInteger(coverage.counts.flood_events));
assert.ok(Number.isInteger(coverage.label_counts.unknown));
const location = points[0].code;
assert.equal((await json("flood-risk/" + location + "/details", undefined, proxy)).point.code, location);

const generated = await json("flood-risk/generate", { location }, proxy);
assert.equal(generated.length, 1);
assert.equal(generated[0].flood_probability, null);
assert.equal(Date.parse(generated[0].valid_until) - Date.parse(generated[0].issued_at), 86_400_000);
const replay = await json("flood-risk/generate", { location, issued_at: generated[0].issued_at });
assert.equal(replay[0].id, generated[0].id);
assert.ok((await json("flood-risk/history?location=" + location)).some((row) => row.id === generated[0].id));
assert.equal((await json("flood-predictions/train", {})).status, metrics.readiness.status === "insufficient_training_data" ?
  "insufficient_training_data" : "study_design_required");
const prediction = await json("flood-predictions/predict", { location }, proxy);
assert.ok("flood_probability" in prediction);
assert.ok(predictions.every((item) => item.flood_probability >= 0 && item.flood_probability <= 1));
if (!metrics.version) {
  assert.equal(prediction.flood_probability, null);
  assert.equal(metrics.evaluation, null);
}
const rainfall = await json("rainfall/coverage", undefined, proxy);
assert.ok(Array.isArray(rainfall));
assert.equal((await fetch(proxy + "flood-predictions/train", {
  method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
})).status, 404);
console.log("Flood gateway and Next proxy contracts, assessment replay, readiness, and legacy rainfall verified.");
