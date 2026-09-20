module simple_chain(a, b, c, y);
  input a, b, c;
  output y;
  wire n1, n2, n3;

  and u1(n1, a, b);
  xor u2(n2, n1, c);
  not u3(n3, n2);
  buf u4(y, n3);
endmodule
