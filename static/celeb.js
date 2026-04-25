/*******************************************************************
 
 ========= CONFETTI JAVASCRIPT  ========= 
 =========      BY TRELLO       =========
 
 As seen on https://trello.com/10million
 _______________________________________
 
 Copyright © Trello. All rights Reserved.
  _______________________________________
 
 XXX Use for Educational Purposes only XXX
 
 I will not be liable for any damages or legal actions for Using of this material.
 
 *******************************************************************/

 var COLORS,
 Confetti,
 NUM_CONFETTI,
 PI_2,
 canvas_2,
 confetti,
 context_2,
 drawCircle,
 drawCircle2,
 drawCircle3,
 i,
 range,
 xpos;
NUM_CONFETTI = 40;
COLORS = [
 [235, 90, 70],
 [97, 189, 79],
 [242, 214, 0],
 [0, 121, 191],
 [195, 119, 224],
];
PI_2 = 2 * Math.PI;
canvas_2 = document.getElementById("confeti");
context_2 = canvas_2.getContext("2d");
window.w = 0;
window.h = 0;
window.resizeWindow = function () {
 window.w = canvas_2.width = window.innerWidth;
 return (window.h = canvas_2.height = window.innerHeight);
};
window.addEventListener("resize", resizeWindow, !1);
window.onload = function () {
 return setTimeout(resizeWindow, 0);
};
range = function (a, b) {
 return (b - a) * Math.random() + a;
};
drawCircle = function (a, b, c, d) {
 context_2.beginPath();
 context_2.moveTo(a, b);
 context_2.bezierCurveTo(a - 17, b + 14, a + 13, b + 5, a - 5, b + 22);
 context_2.lineWidth = 2;
 context_2.strokeStyle = d;
 return context_2.stroke();
};
drawCircle2 = function (a, b, c, d) {
 context_2.beginPath();
 context_2.moveTo(a, b);
 context_2.lineTo(a + 6, b + 9);
 context_2.lineTo(a + 12, b);
 context_2.lineTo(a + 6, b - 9);
 context_2.closePath();
 context_2.fillStyle = d;
 return context_2.fill();
};
drawCircle3 = function (a, b, c, d) {
 context_2.beginPath();
 context_2.moveTo(a, b);
 context_2.lineTo(a + 5, b + 5);
 context_2.lineTo(a + 10, b);
 context_2.lineTo(a + 5, b - 5);
 context_2.closePath();
 context_2.fillStyle = d;
 return context_2.fill();
};
xpos = 0.9;
document.onmousemove = function (a) {
 return (xpos = a.pageX / w);
};
window.requestAnimationFrame = (function () {
 return (
   window.requestAnimationFrame ||
   window.webkitRequestAnimationFrame ||
   window.mozRequestAnimationFrame ||
   window.oRequestAnimationFrame ||
   window.msRequestAnimationFrame ||
   function (a) {
     return window.setTimeout(a, 5);
   }
 );
})();
Confetti = (function () {
 function a() {
   this.style = COLORS[~~range(0, 5)];
   this.rgb =
     "rgba(" + this.style[0] + "," + this.style[1] + "," + this.style[2];
   this.r = ~~range(2, 6);
   this.r2 = 2 * this.r;
   this.replace();
 }
 a.prototype.replace = function () {
   this.opacity = 0;
   this.dop = 0.03 * range(1, 4);
   this.x = range(-this.r2, w - this.r2);
   this.y = range(-20, h - this.r2);
   this.xmax = w - this.r;
   this.ymax = h - this.r;
   this.vx = range(0, 2) + 8 * xpos - 5;
   return (this.vy = 0.7 * this.r + range(-1, 1));
 };
 a.prototype.draw = function () {
   var a;
   this.x += this.vx;
   this.y += this.vy;
   this.opacity += this.dop;
   1 < this.opacity && ((this.opacity = 1), (this.dop *= -1));
   (0 > this.opacity || this.y > this.ymax) && this.replace();
   if (!(0 < (a = this.x) && a < this.xmax))
     this.x = (this.x + this.xmax) % this.xmax;
   drawCircle(~~this.x, ~~this.y, this.r, this.rgb + "," + this.opacity + ")");
   drawCircle3(
     0.5 * ~~this.x,
     ~~this.y,
     this.r,
     this.rgb + "," + this.opacity + ")"
   );
   return drawCircle2(
     1.5 * ~~this.x,
     1.5 * ~~this.y,
     this.r,
     this.rgb + "," + this.opacity + ")"
   );
 };
 return a;
})();
confetti = (function () {
 var a, b, c;
 c = [];
 i = a = 1;
 for (b = NUM_CONFETTI; 1 <= b ? a <= b : a >= b; i = 1 <= b ? ++a : --a)
   c.push(new Confetti());
 return c;
})();
window.step = function () {
 var a, b, c, d;
 requestAnimationFrame(step);
 context_2.clearRect(0, 0, w, h);
 d = [];
 b = 0;
 for (c = confetti.length; b < c; b++) (a = confetti[b]), d.push(a.draw());
 return d;
};
step();
