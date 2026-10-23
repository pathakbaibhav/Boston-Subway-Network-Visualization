import sys

MAX_FLOAT = sys.float_info.max

class Node:
    def __init__(self, label, x, y, index):
        self.label = label
        self.x = x
        self.y = y
        self.index = index

class Edge:
    def __init__(self, from_node, to_node, minutes):
        self.from_node = from_node
        self.to_node = to_node
        self.minutes = minutes

    def get_from_node(self):
        return self.from_node

    def get_to_node(self):
        return self.to_node

    def get_minutes(self):
        return self.minutes

# Assuming nodes and edges are lists of Node and Edge objects respectively
nodes = []
edges = []

# Assuming nodeCount and edgeCount are the counts of nodes and edges respectively
node_count = len(nodes)
edge_count = len(edges)

active_nodes = []
active_edges = []

adjacency_matrix = []
adjacency_matrix_indices = []

def initialize_active_data_structures():
    global active_nodes, active_edges
    active_nodes = [True] * node_count
    active_edges = [True] * edge_count

def initialize_adjacency_matrix():
    global adjacency_matrix, adjacency_matrix_indices
    adjacency_matrix = [[-1.0] * node_count for _ in range(node_count)]
    adjacency_matrix_indices = [[-1] * node_count for _ in range(node_count)]
    for i in range(edge_count):
        e = edges[i]
        from_index = e.get_from_node().index
        to_index = e.get_to_node().index
        adjacency_matrix[from_index][to_index] = e.get_minutes()
        adjacency_matrix[to_index][from_index] = e.get_minutes()
        adjacency_matrix_indices[from_index][to_index] = i
        adjacency_matrix_indices[to_index][from_index] = i

def shortest_path(start, end):
    global active_nodes, active_edges
    if start == end:
        active_nodes = [False] * node_count
        active_nodes[start] = True
        active_edges = [False] * edge_count
        return 0.0

    distances = [MAX_FLOAT] * node_count
    prev_vertices = [-1] * node_count
    visited_vertices = [False] * node_count
    visited_count = 0
    current_vertex = start
    distances[current_vertex] = 0.0

    while visited_count < node_count:
        visited_vertices[current_vertex] = True
        visited_count += 1
        for i in range(node_count):
            if adjacency_matrix[current_vertex][i] != -1.0 and not visited_vertices[i]:
                new_dist = distances[current_vertex] + adjacency_matrix[current_vertex][i]
                if new_dist < distances[i]:
                    distances[i] = new_dist
                    prev_vertices[i] = current_vertex
        min_dist = MAX_FLOAT
        for i in range(node_count):
            if not visited_vertices[i] and distances[i] < min_dist:
                current_vertex = i
                min_dist = distances[i]

    active_nodes = [False] * node_count
    active_edges = [False] * edge_count

    # Determine the shortest path
    start_node = end
    end_node = prev_vertices[end]
    active_nodes[start_node] = True
    active_nodes[end_node] = True
    active_edges[adjacency_matrix_indices[start_node][end_node]] = True
    while end_node != start:
        start_node = end_node
        end_node = prev_vertices[start_node]
        active_nodes[end_node] = True
        active_edges[adjacency_matrix_indices[start_node][end_node]] = True

    return distances[end]
