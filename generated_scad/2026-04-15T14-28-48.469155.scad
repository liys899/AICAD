p0_length = 40.0;
p0_head_across_flats = 13.0;
p0_head_height = 5.3;
p0_shank_diameter = 8.0;
p1_outer_diameter = 16.0;
p1_inner_diameter = 8.4;
p1_thickness = 1.6;
p2_across_flats = 13.0;
p2_thickness = 6.5;
p2_hole_diameter = 8.4;

module part_0() {
  union() {
    translate([0,0,((p0_length) - (p0_head_height)) / 2.0]) cylinder(h=p0_head_height, r=(p0_head_across_flats) / 1.7320508075688772, center=true, $fn=6);
    translate([0,0,-(p0_head_height) / 2.0]) cylinder(h=p0_length, r=(p0_shank_diameter) / 2.0, center=true, $fn=64);
  }
}

module part_1() {
  difference() {
    cylinder(h=p1_thickness, r=(p1_outer_diameter) / 2.0, center=true, $fn=96);
    cylinder(h=(p1_thickness) + 0.2, r=(p1_inner_diameter) / 2.0, center=true, $fn=64);
  }
}

module part_2() {
  difference() {
    cylinder(h=p2_thickness, r=(p2_across_flats) / 1.7320508075688772, center=true, $fn=6);
    cylinder(h=(p2_thickness) + 0.2, r=(p2_hole_diameter) / 2.0, center=true, $fn=64);
  }
}

translate([0.0, 0.0, 0.0])
rotate([0.0, 0.0, 0.0]) {
  part_0();
}
