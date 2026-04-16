p0_radius = 10.0;
p0_length = 100.0;
p1_radius = 1.0;
p1_height = 100.2;

module part_0() {
  cylinder(r=p0_radius, h=p0_length, $fn=96);
}

module part_1() {
  cylinder(r=p1_radius, h=p1_height, $fn=96);
}

difference() {
  part_0();
  part_1();
}
