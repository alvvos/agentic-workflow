'use strict';
(function () {
  var PANELS = [
    { panel: 'panel-ejecutivo-content', overlay: 'pm-render-overlay'   },
    { panel: 'bi-dynamic-content',      overlay: 'bi-render-overlay'   },
    { panel: 'pred-publica-content',    overlay: 'pred-render-overlay' },
  ];

  /* Wait until every Plotly graph inside `container` has fired plotly_afterplot.
     Returns a cancel() function to abort (e.g. when fresh content arrives). */
  function waitForAllPlots(container, onDone) {
    var cancelled    = false;
    var plotCount    = 0;
    var doneCount    = 0;
    var noPlotTimer  = null;
    var hardTimer    = null;
    var sub          = null;  // MutationObserver watching for new plots

    function cancel() {
      cancelled = true;
      if (sub) { sub.disconnect(); sub = null; }
      clearTimeout(noPlotTimer);
      clearTimeout(hardTimer);
    }

    function finish() {
      if (cancelled) return;
      cancel();
      onDone();
    }

    function onPlotRendered() {
      doneCount++;
      if (doneCount >= plotCount) finish();
    }

    function attachToPlot(plot) {
      if (plotCount === 0) {
        clearTimeout(noPlotTimer);  // first plot appeared — cancel no-plot timer
      }
      plotCount++;
      plot.on('plotly_afterplot', function handler() {
        plot.off('plotly_afterplot', handler);
        onPlotRendered();
      });
    }

    /* Watch for .js-plotly-plot elements appearing in the subtree (React mounts
       dcc.Graph asynchronously after the parent div lands in the DOM). */
    sub = new MutationObserver(function (mutations) {
      mutations.forEach(function (m) {
        m.addedNodes.forEach(function (node) {
          if (node.nodeType !== 1) return;
          var plots = (node.classList && node.classList.contains('js-plotly-plot'))
            ? [node]
            : Array.from(node.querySelectorAll('.js-plotly-plot'));
          plots.forEach(attachToPlot);
        });
      });
    });
    sub.observe(container, { childList: true, subtree: true });

    /* Also pick up plots already present when we start (React can be synchronous). */
    Array.from(container.querySelectorAll('.js-plotly-plot')).forEach(attachToPlot);

    /* If no plots appear within 800 ms → content has no graphs, hide overlay. */
    noPlotTimer = setTimeout(function () {
      if (!cancelled && plotCount === 0) finish();
    }, 800);

    /* Hard ceiling: never block the UI for more than 15 s. */
    hardTimer = setTimeout(finish, 15000);

    return cancel;
  }

  /* Attach a content-change observer to one panel/overlay pair. */
  function guardPanel(panelId, overlayId) {
    function tryStart() {
      var panel   = document.getElementById(panelId);
      var overlay = document.getElementById(overlayId);
      if (!panel || !overlay) { setTimeout(tryStart, 500); return; }

      var cancelCurrent = null;

      /* Fire whenever Dash replaces the panel's direct children. */
      new MutationObserver(function () {
        if (cancelCurrent) { cancelCurrent(); cancelCurrent = null; }
        overlay.style.display = 'flex';
        cancelCurrent = waitForAllPlots(panel, function () {
          overlay.style.display = 'none';
          cancelCurrent = null;
        });
      }).observe(panel, { childList: true });
    }
    tryStart();
  }

  function init() {
    PANELS.forEach(function (p) { guardPanel(p.panel, p.overlay); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
