function startStarfield() {
  const canvas = document.getElementById("starfield");
  const ctx = canvas.getContext("2d");

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener("resize", resize);

  const stars = [];
  for (let i = 0; i < 250; i++) {
    stars.push({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      z: Math.random() * 2 + 0.5
    });
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    ctx.fillStyle = "white";

    for (let s of stars) {
      ctx.fillRect(s.x, s.y, 2, 3 * s.z);
      s.y += s.z * 2;

      if (s.y > canvas.height) {
        s.y = 0;
        s.x = Math.random() * canvas.width;
      }
    }

    requestAnimationFrame(draw);
  }

  draw();
}
