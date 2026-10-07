#ifndef __PERFORMANCE_TIMER_ITEMS_H
#define __PERFORMANCE_TIMER_ITEMS_H

/* One bit per deterministic map spawn category: rocket, camo, overshield. */
void performance_timer_items_initialize(void);
unsigned performance_timer_items_due(long previous, long current);
/* Upcoming reminders expire before the wave's ten-second countdown. Each
 * category's deadline is in host match ticks; short spawn periods use their
 * own smaller lead instead of announcing a wave a full period in advance. */
unsigned performance_timer_items_upcoming(long previous, long current,
    long lead, long deadlines[3]);

#endif
