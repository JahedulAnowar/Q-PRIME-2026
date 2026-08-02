"use client";

import { useState, useEffect, useCallback } from "react";

import { SQL_TABLE } from "@/lib/sql";

import { withBasePath } from "@/lib/basePath";

export const useAllSensorsData = ({
    hours = 1,
    databaseLayer,
    autoRefreshInterval = 0,
}) => {
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);


    // Query for hourly all sensors stats
    const query = `SELECT resource.device_name, contextValue, COUNT(*) AS event_count
        FROM ${SQL_TABLE}
        WHERE FROM_UNIXTIME(timestamp) >= NOW() - INTERVAL '${hours}' HOUR
        AND FROM_UNIXTIME(timestamp) < NOW()
        GROUP BY resource.device_name, contextValue;`;

    // const queryEdge = `SELECT *
    //     FROM ${SQL_TABLE}
    //     AND to_timestamp(timestamp) >= NOW() - INTERVAL '${hours}' hour
    //     AND to_timestamp(timestamp) < NOW()
    //     ORDER BY timestamp DESC;`;

    const fetchAllSensorStats = useCallback(async () => {
        //query

        try {
            setLoading(true);
            setError(null);

            const response = await fetch(withBasePath("/api/dashboard/all"), {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ query, scope: databaseLayer }),
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(
                    errorData.error || errorData.message ||
                        `HTTP error! status: ${response.status}`
                );
            }

            const result = await response.json();
            setData(result.data || []);
        } catch (err) {
            setError(err instanceof Error ? err.message : "An error occurred");
            console.error("Error fetching device stats:", err);
        } finally {
            setLoading(false);
        }
    }, [hours, databaseLayer]);

    useEffect(() => {
        fetchAllSensorStats();
        // Set up auto refresh if interval is provided
        let intervalId;
        if (autoRefreshInterval > 0) {
            intervalId = setInterval(fetchAllSensorStats, autoRefreshInterval);
        }

        // Clean up interval on unmount
        return () => {
            if (intervalId) {
                clearInterval(intervalId);
            }
        };
    }, [fetchAllSensorStats, autoRefreshInterval]);

    return {
        data,
        loading,
        error,
        refresh: fetchAllSensorStats,
    };
};
export default useAllSensorsData;
