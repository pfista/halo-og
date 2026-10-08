/* Physical desktop GL render pixels; game/HUD coordinates remain 480 lines. */
#ifndef HALO_DESKTOP_RENDER_SCALE_H
#define HALO_DESKTOP_RENDER_SCALE_H

static void halo_desktop_render_scale(long requested, long logical_width,
    long drawable_width, long drawable_height, long maximum, float scale[2])
{
    double x = scale[0], y = scale[1], bound;
    if (requested != -1 && requested != 0 && requested != 480 && requested != 720 &&
        requested != 1080 && requested != 1440 && requested != 2160) requested = -1;
    if (requested > 0) x = y = (double)requested / 480.0;
    else if (requested == 0 && drawable_width > 0 && drawable_height > 0)
    {
        x = (double)drawable_width / logical_width;
        y = (double)drawable_height / 480.0;
        x = y = x < y ? x : y;
    }
    /* A minimized/not-yet-created drawable keeps the caller's valid scale.
     * Bound both axes uniformly so very wide/large displays preserve shape
     * without exceeding the driver's texture attachment limit. */
    if (maximum < 1) maximum = 4096;
    bound = (double)maximum / logical_width;
    if (bound > (double)maximum / 480.0) bound = (double)maximum / 480.0;
    if (x > bound || y > bound)
    {
        double reduction = bound / (x > y ? x : y);
        x *= reduction;
        y *= reduction;
    }
    scale[0] = (float)x;
    scale[1] = (float)y;
}

#endif
