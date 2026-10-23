"""Baseline for benchmarks: the original HW4 approach (legacy/HW4-code/Ex_1_2_4/ShortestPath.py).

Ported faithfully but without globals: a dense V x V adjacency matrix of minutes plus a second
V x V matrix of edge indices, and Dijkstra that scans every vertex to pick the next one and every
matrix column to relax neighbors, i.e. O(V^2) per query. Station-level graph, no transfer penalty.
"""

import sys

MAX_FLOAT = sys.float_info.max


class MatrixGraph:
    def __init__(self, network):
        self.stations = [s.id for s in network.stations]
        self.index = {sid: i for i, sid in enumerate(self.stations)}
        n = len(self.stations)
        self.adjacency_matrix = [[MAX_FLOAT] * n for _ in range(n)]
        self.adjacency_matrix_indices = [[-1] * n for _ in range(n)]
        for edge_index, seg in enumerate(network.segments):
            a, b = self.index[seg.from_station], self.index[seg.to_station]
            # Parallel lines between the same stations collapse to the faster one.
            if seg.minutes < self.adjacency_matrix[a][b]:
                self.adjacency_matrix[a][b] = self.adjacency_matrix[b][a] = seg.minutes
                self.adjacency_matrix_indices[a][b] = self.adjacency_matrix_indices[b][a] = edge_index

    def shortest_path(self, origin: str, destination: str) -> tuple[float, list[str]]:
        start, end = self.index[origin], self.index[destination]
        node_count = len(self.stations)
        if start == end:
            return 0.0, [origin]

        distances = [MAX_FLOAT] * node_count
        prev_vertices = [-1] * node_count
        visited_vertices = [False] * node_count
        visited_count = 0
        current_vertex = start
        distances[current_vertex] = 0.0
        matrix = self.adjacency_matrix

        while visited_count < node_count:
            visited_vertices[current_vertex] = True
            visited_count += 1

            for i in range(node_count):
                if matrix[current_vertex][i] != MAX_FLOAT and not visited_vertices[i]:
                    new_dist = distances[current_vertex] + matrix[current_vertex][i]
                    if new_dist < distances[i]:
                        distances[i] = new_dist
                        prev_vertices[i] = current_vertex

            min_dist = MAX_FLOAT
            for i in range(node_count):
                if not visited_vertices[i] and distances[i] < min_dist:
                    current_vertex = i
                    min_dist = distances[i]

            if visited_vertices[end]:
                break

        path = []
        current_vertex = end
        while current_vertex != -1:
            path.insert(0, self.stations[current_vertex])
            current_vertex = prev_vertices[current_vertex]
        return distances[end], path
