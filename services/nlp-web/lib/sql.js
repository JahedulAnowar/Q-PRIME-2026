/**
 * The logical table exposed by the Q-PRIME query API.
 * `NEXT_PUBLIC_SQL_TABLE_NAME` can override the default name.
 */
export const SQL_TABLE =
    process.env.NEXT_PUBLIC_SQL_TABLE_NAME || "qprime.continuum";

/** The combined external view is the default; the others are filters. */
export const DATA_SCOPES = [
    { value: "continuum", label: "Continuum (edge + cloud)", short: "Continuum" },
    { value: "edge", label: "Edge only", short: "Edge" },
    { value: "cloud", label: "Cloud only", short: "Cloud" },
];

export const DEFAULT_SCOPE = "continuum";
