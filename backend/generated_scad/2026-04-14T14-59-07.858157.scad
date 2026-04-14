outer_radius = 30.0;
inner_radius = 20.0;
length = 100.0;
difference() {
  cylinder(r=outer_radius, h=length, $fn=96);
  translate([0, 0, -0.01]) cylinder(r=inner_radius, h=length + 0.02, $fn=96);
}
