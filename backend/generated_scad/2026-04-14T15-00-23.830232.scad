radius1 = 30.0;
length1 = 40.0;
radius2 = 20.0;
length2 = 60.0;
total_len = length1 + length2;
union() {
  translate([0, 0, -30.0]) cylinder(r=radius1, h=length1, center=true, $fn=96);
  translate([0, 0, 20.0]) cylinder(r=radius2, h=length2, center=true, $fn=96);
}
