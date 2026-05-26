"""Bracket visualization handler (Phase 15).

Pure-layer module — emits Graphviz DOT source from a MatchGraph DAG.
No Discord imports, no `graphviz` Python import (the adapter renders).

Source: /tmp/claude-1001/tourney-inspect/match_graph.py:353-545. We
follow source's structure (cluster grouping by label prefix, HTML-
table nodes with per-player colored rows, projected winners/losers
for unfinished matches) but inline the `id2pydot` encoding so we
don't drag in the pydot dep.
"""

from collections import defaultdict


def id2dot(idx):
    """Encode an int id as an alphabetic node name. Mirrors source
    `id2pydot` (A, B, …, Z, AA, …, AZ, BA, …)."""
    if idx < 0:
        raise ValueError(f"id2dot index must be non-negative, got {idx}")
    name = ""
    x = idx + 1
    while x > 0:
        x -= 1
        name = chr(ord("A") + (x % 26)) + name
        x //= 26
    return name


def _rgb_hex(color):
    """Convert a (r, g, b) tuple → '#RRGGBB' hex. Pass-through if
    already a string."""
    if color is None:
        return "#888888"
    if isinstance(color, str):
        return color
    if isinstance(color, (tuple, list)) and len(color) == 3:
        r, g, b = color
        return f"#{int(r):02x}{int(g):02x}{int(b):02x}"
    return "#888888"


def _player_color(tournament, player):
    """Look up a player's RGB hex string. Falls back to gray."""
    colors = getattr(tournament, "player_colors", {}) or {}
    return _rgb_hex(colors.get(player))


def _player_label(player):
    """Stringify a player for display in the bracket. Strips non-
    alphanumeric chars (source convention) and caps at 15 chars."""
    if player is None:
        return ""
    text = getattr(player, "parse", lambda mention=False: str(player))(False)
    text = str(text).upper()
    cleaned = "".join(c for c in text if c.isalnum() or c in " ()")
    return cleaned[:15]


def _node_rank(node):
    """Source's rank() = depth-from-victory propagated via children.
    For DOT layout, we use the node's loser_gets if set, else 0."""
    r = getattr(node, "loser_gets", None)
    if r is None:
        return 0
    return r


def _cluster_for(node):
    """First-token of node.label is the cluster key
    (LOSERS/WINNERS/GRAND/INVISIBLE/DEADASS)."""
    if not node.label:
        return "MATCHES"
    return node.label.split(" ")[0].upper()


def _seed_index(tournament, player):
    """Resolve a player's seed index. Falls back to roster index."""
    seeds = getattr(tournament, "seed_by_player", None) or {}
    if player in seeds:
        return seeds[player]
    players = getattr(tournament, "players", []) or []
    try:
        return players.index(player)
    except ValueError:
        return 999_999


def _project_winners_losers(graph, tournament):
    """For each visible node, compute a "projected" winner/loser even
    if the match isn't completed yet (for showing 'WINNER OF X' /
    'LOSER OF X' in upstream slots).

    Walks ancestors of victory_node (deepest-first) and propagates
    projections via parent W/L flags."""
    projected_winners = {}
    projected_losers = {}
    if graph.victory_node is None:
        return projected_winners, projected_losers
    # Collect all nodes via ancestors, deepest-rank-first.
    all_nodes = set(graph.ancestors(graph.victory_node, include_completed=True))
    nodes_sorted = sorted(
        all_nodes,
        key=lambda n: (_node_rank(n), _cluster_for(n)),
        reverse=False,
    )
    for node in nodes_sorted:
        if node.completed():
            projected_winners[node] = node.winner()
            projected_losers[node] = node.loser()
        else:
            # Project from parents' W/L assignments via projected_*.
            if len(node.players) == 2:
                ordered = sorted(node.players,
                                 key=lambda p: _seed_index(tournament, p))
                projected_winners[node] = ordered[0]
                projected_losers[node] = ordered[-1]
            else:
                projected = []
                for parent_id, flag in node.parents.items():
                    parent = graph.nodes_by_id.get(parent_id)
                    if parent is None:
                        continue
                    if flag == "W" and parent in projected_winners:
                        projected.append(projected_winners[parent])
                    elif flag == "L" and parent in projected_losers:
                        projected.append(projected_losers[parent])
                if projected:
                    ordered = sorted(
                        projected, key=lambda p: _seed_index(tournament, p))
                    projected_winners[node] = ordered[0]
                    projected_losers[node] = ordered[-1]
    return projected_winners, projected_losers


def dot_source(graph, tournament):
    """Build a Graphviz DOT string from a MatchGraph DAG.

    Returns the DOT source (str). Render via `graphviz.Source(...).
    render(format='png')` — the adapter does that.
    """
    if graph is None or graph.victory_node is None:
        return "digraph bracket {\n}\n"

    projected_winners, projected_losers = _project_winners_losers(
        graph, tournament)

    # Collect visible nodes (skip byes/DQs).
    all_nodes = list(graph.ancestors(graph.victory_node,
                                     include_completed=True))
    filtered = []
    for n in all_nodes:
        if n.is_bye():
            continue
        filtered.append(n)

    # Sort: by rank desc, then cluster priority, then seed.
    def sort_key(n):
        label = n.label or ""
        if label.startswith("WINNERS"):
            cluster_pri = 0.5
        elif label.startswith("INVISIBLE"):
            cluster_pri = 0.25
        else:
            cluster_pri = 0
        winner_seed = _seed_index(tournament, projected_winners.get(n))
        return (-_node_rank(n), -cluster_pri, winner_seed)

    filtered.sort(key=sort_key)

    # Build id mapping + cluster grouping.
    node2id = {}
    node_clusters = defaultdict(list)
    for i, node in enumerate(filtered):
        node2id[node] = id2dot(i)
        node_clusters[_cluster_for(node)].append(i)

    # Build DOT header.
    out = []
    out.append("digraph bracket {")
    out.append('\tlabelloc="t"')
    out.append('\trankdir="LR"')
    out.append('\tfontname="Open Sans Bold"')
    out.append('\tbgcolor="#222222"')
    out.append('')
    out.append('\tnode [')
    out.append('\t\tshape="plaintext"')
    out.append('\t\tfontname="Open Sans Bold"')
    out.append('\t]')
    out.append('')

    # Subgraph clusters — source order.
    cluster_order = ["LOSERS", "INVISIBLE", "WINNERS", "GRAND", "DEADASS"]
    extra_clusters = [c for c in node_clusters.keys() if c not in cluster_order]
    for cluster in cluster_order + extra_clusters:
        if cluster not in node_clusters:
            continue
        out.append(f"\tsubgraph cluster_{cluster} {{")
        out.append(f'\t\tlabel=<<b>{cluster}</b>>')
        out.append("\t\tcenter=true")
        for idx in node_clusters[cluster]:
            node = filtered[idx]
            out.append(_format_node(
                node, idx, cluster, node2id,
                projected_winners, projected_losers,
                graph, tournament,
            ))
        out.append("\t}")

    # Edges — W links only (source comments out L links).
    for node in filtered:
        if node.is_bye():
            continue
        for child_id, flag in node.children.items():
            child = graph.nodes_by_id.get(child_id)
            if child is None or child not in node2id:
                continue
            # Skip byes; chase to the first non-bye descendant.
            kid = child
            chase_flag = flag
            while kid.is_bye():
                next_kid = None
                for grandkid_id, gflag in kid.children.items():
                    if gflag == chase_flag:
                        next_kid = graph.nodes_by_id.get(grandkid_id)
                        break
                if next_kid is None or next_kid is kid:
                    break
                kid = next_kid
            if kid.is_bye() or kid not in node2id:
                continue
            if flag == "W":
                # Source skips WINNERS→DEADASS edges.
                if (node.label.startswith("WINNERS")
                        and kid.label.startswith("DEADASS")):
                    continue
                out.append(
                    f'\t{node2id[node]} -> {node2id[kid]} '
                    f'[penwidth=4, color="lightgray"]')

    # Rank groups — keep same-rank nodes aligned.
    ranks = defaultdict(list)
    for node in filtered:
        ranks[_node_rank(node)].append(node)
    for r in sorted(ranks.keys(), reverse=True):
        names = "; ".join(node2id[n] for n in ranks[r])
        out.append("\t{ rank=same; " + names + "; }")

    out.append("}")
    return "\n".join(out) + "\n"


def _format_node(node, idx, cluster, node2id, projected_winners,
                 projected_losers, graph, tournament):
    """Emit the DOT lines for a single node (HTML-table label)."""
    dot_id = node2id[node]
    streamed_fill = '"#aa33ff"' if node.streamed else '"#111111"'
    lines = [f"\t\t{dot_id} ["]
    lines.append("\t\t\tstyle=filled")
    lines.append(f"\t\t\tfillcolor={streamed_fill}")
    if cluster == "INVISIBLE":
        lines.append("\t\t\tstyle=invis,")
    lines.append("\t\t\tlabel=<")
    lines.append('\t\t\t\t<table border="0" cellborder="1" cellspacing="0">')
    node_color = "#ffaaaa" if cluster == "LOSERS" else "#faa7e9"
    header_color = "#ff9999" if cluster == "LOSERS" else "#f890f7"
    lines.append(
        f'\t\t\t\t\t<tr><td colspan="2" bgcolor="{header_color}">'
        f'<b>{dot_id}: {node.label}</b></td></tr>'
    )
    # Player rows.
    for k, player in enumerate(node.players):
        player_color = _player_color(tournament, player)
        name = _player_label(player)
        if node.completed():
            score_color = "gold" if player == node.winner() else "silver"
        elif node.awake():
            score_color = "white"
        else:
            score_color = node_color
        score_value = node.score[k] if node.completed() else "-"
        lines.append(
            f'\t\t\t\t\t<tr><td align="left" bgcolor="{player_color}">'
            f'{name}</td><td bgcolor="{score_color}">{score_value}</td></tr>'
        )
    # Projected WINNER OF X / LOSER OF X rows for slots without 2 players.
    if len(node.players) < 2:
        for parent_id, parent_flag in node.parents.items():
            parent = graph.nodes_by_id.get(parent_id)
            if parent is None:
                continue
            if parent.completed() or parent.is_bye():
                continue
            if parent_flag == "W":
                player = projected_winners.get(parent)
                tag = "WINNER OF"
            else:
                player = projected_losers.get(parent)
                tag = "LOSER OF"
            if player is None or parent not in node2id:
                continue
            row_color = _player_color(tournament, player)
            lines.append(
                f'\t\t\t\t\t<tr><td align="left" bgcolor="{row_color}">'
                f'{tag} {node2id[parent]}</td><td bgcolor="{node_color}">-</td></tr>'
            )
    lines.append("\t\t\t\t</table>>")
    lines.append("\t\t]")
    return "\n".join(lines)
