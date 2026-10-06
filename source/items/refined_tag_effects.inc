/* Meeting-requested content refinements, applied only to loaded native tags.
 * These intentionally refine retail quirks; they are not Xbox fidelity fixes.
 * Keep cache files and authored replacement effects/materials unchanged. */
static void refined_tag_effects_initialize_for_new_map(void)
{
	long projectile_index = tag_loaded(PROJECTILE_DEFINITION_TAG, "weapons\\pistol\\bullet");
	long collision_index = tag_loaded('coll', "powerups\\over shield\\over shield");

	if (projectile_index != NONE)
	{
		struct projectile_definition *projectile = projectile_definition_get(projectile_index);
		long hollow_effect = tag_loaded(EFFECT_DEFINITION_TAG,
			"weapons\\pistol\\effects\\impact metal hollow reflect");
		long thick_effect = tag_loaded(EFFECT_DEFINITION_TAG,
			"weapons\\pistol\\effects\\impact metal thick reflect");

		if (projectile && projectile->projectile.material_responses.address &&
			projectile->projectile.material_responses.count > _material_thick_metal &&
			hollow_effect != NONE && thick_effect != NONE)
		{
			struct projectile_material_response_definition *hollow = TAG_BLOCK_GET_ELEMENT(
				&projectile->projectile.material_responses, _material_hollow_metal,
				struct projectile_material_response_definition);
			struct projectile_material_response_definition const *thick = TAG_BLOCK_GET_ELEMENT(
				&projectile->projectile.material_responses, _material_thick_metal,
				struct projectile_material_response_definition);

			/* The reviewed stock and community inputs use the hollow reflect
			 * effect as their default response. Retarget only that reference;
			 * retain ricochet, penetration, damage and all response parameters. */
			if (hollow->default_effect.group_tag == EFFECT_DEFINITION_TAG &&
				hollow->default_effect.index == hollow_effect &&
				thick->default_effect.group_tag == EFFECT_DEFINITION_TAG &&
				thick->default_effect.index == thick_effect)
				hollow->default_effect = thick->default_effect;
		}
	}

	if (collision_index != NONE)
	{
		struct collision_model *collision = collision_model_definition_get(collision_index);
		long material_index;

		if (!collision || !collision->resistance.materials.address)
			return;
		for (material_index = 0; material_index < collision->resistance.materials.count; material_index++)
		{
			struct damage_resistance_material *material = TAG_BLOCK_GET_ELEMENT(
				&collision->resistance.materials, material_index, struct damage_resistance_material);
			if (material->material_type == _material_dirt)
				material->material_type = _material_engineer_force_field;
		}
	}
}
