function startStarfield() {
  const canvas = document.getElementById("starfield");
  const ctx = canvas.getContext("2d");

  let w, h;
  function resize() {
    w = canvas.width = window.innerWidth;
    h = canvas.height = window.innerHeight;
  }
  window.onresize = resize;
  resize();

  const stars = [];
  for (let i = 0; i < 200; i++) {
    stars.push({
      x: Math.random() * w,
      y: Math.random() * h,
      z: Math.random() * 3 + 1
    });
  }

  function draw() {
    ctx.fillStyle = "black";
    ctx.fillRect(0, 0, w, h);

    ctx.fillStyle = "white";
    stars.forEach(s => {
      ctx.fillRect(s.x, s.y, 2, s.z);

      s.y += s.z * 1.2;
      if (s.y > h) {
        s.y = 0;
        s.x = Math.random() * w;
      }
    });

    requestAnimationFrame(draw);
  }

  draw();
}
