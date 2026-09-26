-- Route-level demand, revenue and reliability.

-- name: route_performance
SELECT
    route,
    origin,
    destination,
    MAX(distance_miles)                                   AS distance_miles,
    COUNT(*)                                              AS flights,
    COUNT(DISTINCT airline)                               AS airlines,
    SUM(passengers)                                       AS passengers,
    ROUND(SUM(revenue), 2)                                AS revenue,
    ROUND(AVG(delay_minutes), 2)                          AS avg_delay_minutes,
    ROUND(AVG(is_on_time), 4)                             AS on_time_rate,
    ROUND(AVG(is_cancelled), 4)                           AS cancellation_rate,
    RANK() OVER (ORDER BY SUM(revenue) DESC)              AS revenue_rank,
    RANK() OVER (ORDER BY SUM(passengers) DESC)           AS passenger_rank
FROM flights
GROUP BY route, origin, destination
ORDER BY revenue DESC;

-- name: top_delayed_routes
-- Routes with at least 100 flights, ranked by average departure delay.
SELECT
    route,
    COUNT(*)                        AS flights,
    ROUND(AVG(delay_minutes), 2)    AS avg_delay_minutes,
    ROUND(AVG(is_on_time), 4)       AS on_time_rate,
    ROUND(AVG(is_cancelled), 4)     AS cancellation_rate
FROM flights
GROUP BY route
HAVING COUNT(*) >= 100
ORDER BY avg_delay_minutes DESC
LIMIT 10;

-- name: high_demand_poor_performance
-- Business question: which routes carry the most passengers but run
-- below the network's on-time rate? Top passenger quartile + below-average OTP.
WITH route_stats AS (
    SELECT
        route,
        SUM(passengers)              AS passengers,
        SUM(revenue)                 AS revenue,
        AVG(is_on_time)              AS on_time_rate,
        AVG(delay_minutes)           AS avg_delay_minutes,
        AVG(is_cancelled)            AS cancellation_rate
    FROM flights
    GROUP BY route
),
ranked AS (
    SELECT *, NTILE(4) OVER (ORDER BY passengers DESC) AS demand_quartile
    FROM route_stats
),
network AS (
    SELECT AVG(is_on_time) AS network_on_time_rate FROM flights
)
SELECT
    r.route,
    r.passengers,
    ROUND(r.revenue, 2)                                       AS revenue,
    ROUND(r.on_time_rate, 4)                                  AS on_time_rate,
    ROUND(n.network_on_time_rate, 4)                          AS network_on_time_rate,
    ROUND(r.on_time_rate - n.network_on_time_rate, 4)         AS on_time_gap,
    ROUND(r.avg_delay_minutes, 2)                             AS avg_delay_minutes,
    ROUND(r.cancellation_rate, 4)                             AS cancellation_rate
FROM ranked r
CROSS JOIN network n
WHERE r.demand_quartile = 1
  AND r.on_time_rate < n.network_on_time_rate
ORDER BY r.passengers DESC;

-- name: route_airline_breakdown
-- Same route, different carriers: who runs it best?
SELECT
    route,
    airline,
    COUNT(*)                        AS flights,
    SUM(passengers)                 AS passengers,
    ROUND(AVG(is_on_time), 4)       AS on_time_rate,
    ROUND(AVG(delay_minutes), 2)    AS avg_delay_minutes
FROM flights
WHERE route IN (
    SELECT route FROM flights GROUP BY route HAVING COUNT(DISTINCT airline) > 1
)
GROUP BY route, airline
ORDER BY route, on_time_rate DESC;
