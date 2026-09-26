-- Passenger volume, cabin mix, fares and revenue.
-- Cancelled flights carry 0 passengers, so they contribute no revenue.

-- name: cabin_class_summary
SELECT
    b.cabin_class,
    SUM(b.passengers)                                              AS passengers,
    ROUND(1.0 * SUM(b.passengers) / SUM(SUM(b.passengers)) OVER (), 4) AS passenger_share,
    ROUND(SUM(b.revenue), 2)                                       AS revenue,
    ROUND(SUM(b.revenue) / SUM(SUM(b.revenue)) OVER (), 4)         AS revenue_share,
    ROUND(SUM(b.revenue) / SUM(b.passengers), 2)                   AS avg_ticket_price
FROM bookings b
JOIN flights f USING (flight_id)
WHERE f.is_cancelled = 0
GROUP BY b.cabin_class
ORDER BY avg_ticket_price;

-- name: airline_revenue
SELECT
    f.airline,
    SUM(b.passengers)                                          AS passengers,
    ROUND(SUM(b.revenue), 2)                                   AS revenue,
    ROUND(SUM(b.revenue) / SUM(SUM(b.revenue)) OVER (), 4)     AS revenue_share,
    ROUND(SUM(b.revenue) / SUM(b.passengers), 2)               AS avg_ticket_price,
    ROUND(SUM(CASE WHEN b.cabin_class = 'Business' THEN b.revenue ELSE 0 END)
          / SUM(b.revenue), 4)                                 AS business_revenue_share
FROM bookings b
JOIN flights f USING (flight_id)
GROUP BY f.airline
ORDER BY revenue DESC;

-- name: monthly_passengers
SELECT
    f.month,
    SUM(b.passengers)                                                      AS passengers,
    SUM(CASE WHEN b.cabin_class = 'Economy' THEN b.passengers ELSE 0 END)  AS economy,
    SUM(CASE WHEN b.cabin_class = 'Premium Economy' THEN b.passengers ELSE 0 END) AS premium_economy,
    SUM(CASE WHEN b.cabin_class = 'Business' THEN b.passengers ELSE 0 END) AS business,
    ROUND(SUM(b.revenue), 2)                                               AS revenue,
    ROUND(SUM(b.revenue) / SUM(b.passengers), 2)                           AS avg_ticket_price,
    ROUND(1.0 * SUM(b.passengers)
          / LAG(SUM(b.passengers)) OVER (ORDER BY f.month) - 1, 4)         AS passenger_mom_change
FROM bookings b
JOIN flights f USING (flight_id)
GROUP BY f.month
ORDER BY f.month;

-- name: top_revenue_routes
SELECT
    f.route,
    SUM(b.passengers)                                          AS passengers,
    ROUND(SUM(b.revenue), 2)                                   AS revenue,
    ROUND(SUM(b.revenue) / SUM(SUM(b.revenue)) OVER (), 4)     AS revenue_share,
    ROUND(SUM(b.revenue) / SUM(b.passengers), 2)               AS avg_ticket_price,
    ROUND(SUM(b.revenue) / COUNT(DISTINCT f.flight_id), 2)     AS revenue_per_flight
FROM bookings b
JOIN flights f USING (flight_id)
GROUP BY f.route
ORDER BY revenue DESC
LIMIT 10;
