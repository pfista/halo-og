"""Exercise the production discovery gate with nested visible/hidden widgets."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("clang"), "clang required")
class DirectoryVisibility(unittest.TestCase):
    def test_hidden_ancestors_and_missing_client_stop_discovery(self):
        source = (ROOT / "source/interface/ui_widget_game_data_input_functions.c").read_text()
        production = block(source, "static struct network_advertised_game *server_list_directory_games(")
        fixture = r'''
#include <assert.h>
#include <stddef.h>
#define FALSE 0
struct widget_instance { int visible; struct widget_instance *parent; };
struct network_game_client { int unused; };
struct network_advertised_game { int unused; };
static struct network_advertised_game games[1];
static unsigned queries, stops;
static int browsing;
void game_directory_browse(int enabled) { assert(!enabled); stops++; browsing = enabled; }
struct network_advertised_game *network_game_client_get_directory_games(
    struct network_game_client *client, long *count) {
    assert(client); queries++; browsing = 1; *count = 1; return games;
}
/* PRODUCTION */
int main(void) {
    struct widget_instance root = {1, NULL}, panel = {1, &root}, list = {1, &panel};
    struct network_game_client client = {0};
    long count;
    assert(server_list_directory_games(&list, &client, &count) == games);
    assert(count == 1 && queries == 1 && browsing && !stops);
    list.visible = 0;
    assert(!server_list_directory_games(&list, &client, &count));
    assert(!count && queries == 1 && !browsing && stops == 1);
    list.visible = 1; panel.visible = 0;
    assert(!server_list_directory_games(&list, &client, &count));
    assert(!count && queries == 1 && !browsing && stops == 2);
    panel.visible = 1; root.visible = 0;
    assert(!server_list_directory_games(&list, &client, &count));
    assert(!count && queries == 1 && !browsing && stops == 3);
    root.visible = 1;
    assert(server_list_directory_games(&list, &client, &count) == games);
    assert(count == 1 && queries == 2 && browsing);
    assert(!server_list_directory_games(&list, NULL, &count));
    assert(!count && queries == 2 && !browsing && stops == 4);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="halo-directory-ui-") as temporary:
            probe = Path(temporary) / "probe.c"
            binary = Path(temporary) / "probe"
            probe.write_text(fixture.replace("/* PRODUCTION */", production))
            result = subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                                     str(probe), "-o", str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
