class Edge {
  Node from; 
  Node to; 
  float minutes;
  
  Edge(Node from, Node to, float minutes) {
    this.from = from; 
    this.to = to; 
    this.minutes = minutes;
  }
  
  Node getFromNode() {
    return from;
  }
  
  Node getToNode() {
    return to;
  }
  
  float getMinutes() {
    return minutes;
  }
  
  void draw() {
    stroke(0); 
    strokeWeight(1);
    line(from.x, from.y, to.x, to.y);
  }
}  
