head_across_flats = 16.0;
head_height = 6.0;
shank_diameter = 14.0;
length = 20.0;
circ_r = head_across_flats / 1.7320508075688772;
union() {
  translate([0,0,(length - head_height)/2]) cylinder(h=head_height, r=circ_r, center=true, $fn=6);
  translate([0,0,-head_height/2]) cylinder(h=length, r=shank_diameter/2, center=true, $fn=64);
}
