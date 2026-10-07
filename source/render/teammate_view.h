/* Render-only teammate pane. No local player/controller or simulation state. */
#ifndef __TEAMMATE_VIEW_H
#define __TEAMMATE_VIEW_H

boolean teammate_view_split_screen_active(void);
long teammate_view_get_player_index(short window_index);
long teammate_view_get_first_person_unit_index(short window_index);
short teammate_view_hud_player_count(void);
void teammate_view_draw_label(short window_index);

#endif
