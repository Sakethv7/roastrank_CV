// --- Cinematic Starfield Background ---
// Works for mobile + HF Spaces without lag.

function startStarfield() {
    const canvas = document.getElementById("starfield");
    if (!canvas) return;

    const ctx = canvas.getContext("2d");

    let w, h;
    function resize() {
        w = canvas.width = window.innerWidth;
        h = canvas.height = window.innerHeight;
    }
    resize();
    window.onresize = resize;

    // number of stars based on screen size
    const starCount = Math.floor((w + h) / 15);

    const stars = [];
    for (let i = 0; i < starCount; i++) {
        stars.push({
            x: Math.random() * w,
            y: Math.random() * h,
            z: Math.random() * 0.8 + 0.2, // depth
            size: Math.random() * 1.4 + 0.3,
            speed: Math.random() * 0.3 + 0.05,
        });
    }

    function draw() {
        ctx.fillStyle = "black";
        ctx.fillRect(0, 0, w, h);

        for (const s of stars) {
            ctx.fillStyle = `rgba(255, 255, 255, ${0.4 + Math.random() * 0.6})`;
            ctx.beginPath();
            ctx.arc(s.x, s.y, s.size * s.z, 0, Math.PI * 2);
            ctx.fill();

            // movement
            s.y += s.speed * s.z * 0.8;

            if (s.y > h) {
                s.y = -2;
                s.x = Math.random() * w;
            }
        }

        requestAnimationFrame(draw);
    }

    draw();
}
