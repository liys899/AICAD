across_flats = 10.0;
thickness = 5.0;
hole_diameter = 6.4;
circ_r = across_flats / 1.7320508075688772;
difference() {
  cylinder(h=thickness, r=circ_r, center=true, $fn=6);
  cylinder(h=thickness + 0.2, r=hole_diameter/2, center=true, $fn=64);
}
