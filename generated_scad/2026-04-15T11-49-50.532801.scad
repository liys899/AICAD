p0_radius = 10.0;
p0_length = 100.0;
p1_outer_radius = 10.0;
p1_inner_radius = 3.0;
p1_length = 100.0;

module part_0() {
  cylinder(r=p0_radius, h=p0_length, $fn=96);
}

module part_1() {
  difference() {
    cylinder(r=p1_outer_radius, h=p1_length, $fn=96);
    translate([0, 0, -0.01]) cylinder(r=p1_inner_radius, h=p1_length + 0.02, $fn=96);
  }
}

difference() {
  part_0();
  part_1();
}
