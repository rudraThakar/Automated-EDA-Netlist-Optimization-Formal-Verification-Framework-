module fanout_stress(a, b, c, d, y0, y1, y2, y3);
  input a, b, c, d;
  output y0, y1, y2, y3;
  wire n0, n1, n2, n3;

  and u0(n0, a, b);
  or  u1(n1, a, c);
  xor u2(n2, a, d);
  nand u3(n3, a, b);

  buf u4(y0, n0);
  buf u5(y1, n1);
  buf u6(y2, n2);
  buf u7(y3, n3);
endmodule
