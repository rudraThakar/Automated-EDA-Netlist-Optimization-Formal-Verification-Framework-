module dangling_logic(a, b, c, y);
  input a, b, c;
  output y;
  wire live0, live1, dead0, dead1;

  and u0(live0, a, b);
  or  u1(live1, live0, c);
  buf u2(y, live1);

  and u_dead0(dead0, a, c);
  not u_dead1(dead1, dead0);
endmodule
