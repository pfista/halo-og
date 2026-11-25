/*
DETAIL_DISTANCE.C

How far away models keep their detail and particles are drawn.

The Xbox decides four things from an object's or a particle's size on its
480-line screen, in pixels: which of a model's levels of detail to draw,
whether to draw the model at all, whether to draw its shadow, and whether to
draw a particle. The cutoffs are authored so that the change happens where a
480-line picture can no longer show it. The native builds keep the game's
480-line units while drawing several times as many real pixels, so the same
cutoffs fall where the change is plain to see: models lose detail and
particles vanish in view.

display.detail_distance multiplies those sizes before they are compared with
the cutoffs, which moves each change that many times farther away:

- 0, the default, follows the picture: the real lines drawn for each of the
  game's 480, up to 3. At 480 lines that is 1, exactly the Xbox's.
- 1 is the Xbox's at any resolution.
- 2 and 3 are fixed.

This changes only what is drawn. Footstep and impact effects keep the Xbox's
ten world units from a local camera (material_effect_visible): they carry
sounds, and hearing them farther away would change play.
*/

long config_integer(const char *name);
float halo_screen_pixel_scale(void);

#define DETAIL_DISTANCE_MAXIMUM 3.0f

static float detail_distance = 1.0f;

/* once a frame, before it is drawn (main.c): the setting is looked up by
name, which is too slow for every object and particle */
void halo_detail_distance_refresh(void)
{
	long setting = config_integer("display.detail_distance");
	float scale;

	if (setting >= 1 && setting <= 3)
	{
		scale = (float)setting;
	}
	else
	{
		scale = halo_screen_pixel_scale();
		/* (so written that a scale not a number is 1) */
		if (!(scale >= 1.0f))
			scale = 1.0f;
		if (scale > DETAIL_DISTANCE_MAXIMUM)
			scale = DETAIL_DISTANCE_MAXIMUM;
	}
	detail_distance = scale;
}

float halo_detail_distance(void)
{
	return detail_distance;
}
