/**
 * Query a user-owned edge/cloud data source.
 *
 * The endpoint is external to this repository and must implement the query
 * contract documented in the root README. Q-PRIME only submits read-only SQL
 * and renders the response.
 */

const QUERY_API_URL = (process.env.QUERY_API_URL || "").trim();

// Edge-only / cloud-only are optional filters; anything else is the continuum.
const SCOPE_TO_IS_CLOUD = {
    edge: "false",
    cloud: "true",
    continuum: "continuum",
};

/** Some query engines return struct/array columns as text; revive them. */
function reviveCell(value) {
    if (typeof value !== "string") return value;
    const trimmed = value.trim();
    if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return value;
    try {
        return JSON.parse(trimmed);
    } catch {
        return value;
    }
}

function reviveRow(row) {
    if (!row || typeof row !== "object") return row;
    const out = {};
    for (const [key, value] of Object.entries(row)) {
        out[key] = reviveCell(value);
    }
    return out;
}

/**
 * Run one SQL statement against the continuum.
 * Returns a Response in the shape the visualisation hooks expect.
 */
export async function queryContinuum(request) {
    try {
        const body = await request.json();
        const { query, scope, databaseLayer } = body || {};

        if (!query || !String(query).trim()) {
            return Response.json({ error: "Query is empty" }, { status: 400 });
        }

        if (!QUERY_API_URL) {
            return Response.json(
                { error: "Data source not configured. Set QUERY_API_URL." },
                { status: 503 }
            );
        }

        const isCloud =
            SCOPE_TO_IS_CLOUD[String(scope || databaseLayer || "continuum")] ||
            "continuum";

        const url = new URL(QUERY_API_URL);
        url.searchParams.set("query", query);
        url.searchParams.set("isCloud", isCloud);
        url.searchParams.set("query_timestamp", String(Date.now()));

        const response = await fetch(url, { cache: "no-store" });
        const payload = await response.json();

        if (!response.ok || payload.error) {
            return Response.json(
                { error: payload.error || `External query API error ${response.status}` },
                { status: response.status === 200 ? 500 : response.status }
            );
        }

        const data = (payload.results || []).map(reviveRow);
        return Response.json({
            success: true,
            data,
            count: data.length,
            edgeCount: payload.edge_count ?? 0,
            cloudCount: payload.cloud_count ?? 0,
            scope: payload.scope || "continuum",
        });
    } catch (error) {
        console.error("Continuum query error:", error);
        return Response.json({ error: error.message }, { status: 500 });
    }
}
