-- Airline-level and network-wide operational KPIs.
-- Conventions used throughout:
--   * rates are fractions (0.784 = 78.4%)
--   * on-time rate and average delay are measured over OPERATED flights
--     (AVG ignores the NULLs stored for cancelled flights)
--   * average delay floors early departures at 0 minutes

-- name: executive_kpis
SELECT
    COUNT(*)                                    AS total_flights,
    SUM(is_cancelled)                           AS cancelled_flights,
    ROUND(AVG(is_cancelled), 4)                 AS cancellation_rate,
    ROUND(AVG(is_on_time), 4)                   AS on_time_rate,
    ROUND(AVG(delay_minutes), 2)                AS avg_delay_minutes,
    SUM(passengers)                             AS total_passengers,
    ROUND(SUM(revenue), 2)                      AS total_revenue,
    ROUND(SUM(revenue) / SUM(passengers), 2)    AS avg_fare,
    MIN(flight_date)                            AS period_start,
    MAX(flight_date)                            AS period_end
FROM flights;

-- name: airline_performance
SELECT
    airline,
    COUNT(*)                                                 AS flights,
    ROUND(AVG(is_on_time), 4)                                AS on_time_rate,
    ROUND(1 - AVG(is_on_time), 4)                            AS delay_rate,
    ROUND(AVG(delay_minutes), 2)                             AS avg_delay_minutes,
    ROUND(AVG(CASE WHEN delay_minutes >= 60 THEN 1.0
                   WHEN is_cancelled = 0 THEN 0.0 END), 4)   AS severe_delay_rate,
    ROUND(AVG(is_cancelled), 4)                              AS cancellation_rate,
    SUM(passengers)                                          AS passengers,
    ROUND(SUM(revenue), 2)                                   AS revenue,
    RANK() OVER (ORDER BY AVG(is_on_time) DESC)              AS on_time_rank
FROM flights
GROUP BY airline
ORDER BY on_time_rate DESC;

-- name: monthly_trends
SELECT
    month,
    COUNT(*)                        AS flights,
    ROUND(AVG(is_on_time), 4)       AS on_time_rate,
    ROUND(AVG(delay_minutes), 2)    AS avg_delay_minutes,
    ROUND(AVG(is_cancelled), 4)     AS cancellation_rate,
    SUM(passengers)                 AS passengers,
    ROUND(SUM(revenue), 2)          AS revenue
FROM flights
GROUP BY month
ORDER BY month;

-- name: delay_by_time_of_day
SELECT
    time_of_day,
    COUNT(*)                        AS flights,
    ROUND(AVG(is_on_time), 4)       AS on_time_rate,
    ROUND(AVG(delay_minutes), 2)    AS avg_delay_minutes
FROM flights
GROUP BY time_of_day
ORDER BY MIN(departure_hour);
