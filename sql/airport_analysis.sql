-- Airport-level disruption. Departure performance is attributed to the origin airport.
-- disruption_rate = share of scheduled departures that were cancelled or left 60+ min late.

-- name: airport_performance
WITH departures AS (
    SELECT
        origin                                                  AS airport,
        COUNT(*)                                                AS departures,
        ROUND(AVG(delay_minutes), 2)                            AS avg_delay_minutes,
        ROUND(AVG(is_on_time), 4)                               AS on_time_rate,
        ROUND(AVG(is_cancelled), 4)                             AS cancellation_rate,
        ROUND(AVG(CASE WHEN is_cancelled = 1 OR delay_minutes >= 60
                       THEN 1.0 ELSE 0.0 END), 4)               AS disruption_rate,
        SUM(passengers)                                         AS departing_passengers
    FROM flights
    GROUP BY origin
),
arrivals AS (
    SELECT destination AS airport, COUNT(*) AS arrivals, SUM(passengers) AS arriving_passengers
    FROM flights
    GROUP BY destination
)
SELECT
    d.*,
    a.arrivals,
    a.arriving_passengers,
    d.departing_passengers + a.arriving_passengers              AS total_passengers,
    RANK() OVER (ORDER BY d.disruption_rate DESC)               AS disruption_rank
FROM departures d
JOIN arrivals a USING (airport)
ORDER BY d.disruption_rate DESC;

-- name: delay_by_hour
SELECT
    departure_hour,
    COUNT(*)                        AS flights,
    ROUND(AVG(delay_minutes), 2)    AS avg_delay_minutes,
    ROUND(AVG(is_on_time), 4)       AS on_time_rate,
    ROUND(AVG(is_cancelled), 4)     AS cancellation_rate
FROM flights
GROUP BY departure_hour
ORDER BY departure_hour;

-- name: airport_seasonality
-- Winter (Dec-Feb) vs summer (Jun-Aug) on-time rate by departure airport.
SELECT
    origin                                                                    AS airport,
    ROUND(AVG(CASE WHEN CAST(substr(month, 6, 2) AS INTEGER) IN (12, 1, 2)
                   THEN is_on_time END), 4)                                   AS winter_on_time_rate,
    ROUND(AVG(CASE WHEN CAST(substr(month, 6, 2) AS INTEGER) IN (6, 7, 8)
                   THEN is_on_time END), 4)                                   AS summer_on_time_rate,
    ROUND(AVG(CASE WHEN CAST(substr(month, 6, 2) AS INTEGER) IN (3, 4, 5, 9, 10, 11)
                   THEN is_on_time END), 4)                                   AS shoulder_on_time_rate
FROM flights
GROUP BY origin
ORDER BY winter_on_time_rate;
