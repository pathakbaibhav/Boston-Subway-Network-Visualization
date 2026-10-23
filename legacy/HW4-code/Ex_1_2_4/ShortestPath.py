import sys

MAX_FLOAT = sys.float_info.max

def initializeActiveDataStructures(active_nodes, active_edges, node_count, edge_count):
    for _ in range(node_count):
        active_nodes.append(False)
    for _ in range(edge_count):
        active_edges.append(False)


def initializeAdjacencyMatrix(nodes, edges):
    global adjacency_matrix, adjacency_matrix_indices
    node_count = len(nodes)
    edge_count = len(edges)
    adjacency_matrix = [[MAX_FLOAT] * node_count for _ in range(node_count)]
    adjacency_matrix_indices = [[-1] * node_count for _ in range(node_count)]
    for edge in edges:
        from_index = edge.get_from_node().get_index()
        to_index = edge.get_to_node().get_index()
        adjacency_matrix[from_index][to_index] = edge.get_minutes()
        adjacency_matrix[to_index][from_index] = edge.get_minutes()
        adjacency_matrix_indices[from_index][to_index] = edges.index(edge)
        adjacency_matrix_indices[to_index][from_index] = edges.index(edge)

def shortestPath(start, end, nodes,  active_nodes, active_edges):
    node_count = len(nodes)
    if start == end:
        return 0.0, [start]

    distances = [MAX_FLOAT] * node_count
    prev_vertices = [-1] * node_count
    visited_vertices = [False] * node_count
    visited_count = 0
    current_vertex = start
    distances[current_vertex] = 0.0

    while visited_count < node_count:
        # Mark the current vertex as visited
        visited_vertices[current_vertex] = True
        visited_count += 1
        
        # Update the distances to the neighboring vertices
        for i in range(node_count):
            if adjacency_matrix[current_vertex][i] != MAX_FLOAT and not visited_vertices[i]:
                new_dist = distances[current_vertex] + adjacency_matrix[current_vertex][i]
                if new_dist < distances[i]:
                    distances[i] = new_dist
                    prev_vertices[i] = current_vertex
        
        # Find the next vertex to process
        min_dist = MAX_FLOAT
        for i in range(node_count):
            if not visited_vertices[i] and distances[i] < min_dist:
                current_vertex = i
                min_dist = distances[i]
        
        if visited_vertices[end]:
            break  # We've reached the destination

    # Path reconstruction
    path = []
    current_vertex = end
    while current_vertex != -1:
        path.insert(0, current_vertex)
        current_vertex = prev_vertices[current_vertex]

    # Activate the nodes and edges in the path
    for i in path:
        active_nodes[i] = True

    for i in range(1, len(path)):
        from_index = path[i - 1]
        to_index = path[i]
        edge_index = adjacency_matrix_indices[from_index][to_index]
        active_edges[edge_index] = True

    return distances[end], path
