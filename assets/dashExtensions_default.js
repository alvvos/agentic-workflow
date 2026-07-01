window.dashExtensions = Object.assign({}, window.dashExtensions, {
    default: {
        function0: function(feature, latlng, ctx) {
            const c = feature.properties.color || '#3388ff';
            const icon = L.divIcon({
                className: '',
                html: '<svg width="22" height="32" viewBox="0 0 22 32" xmlns="http://www.w3.org/2000/svg">' +
                    '<path d="M11 0C4.9 0 0 4.9 0 11c0 8.3 11 21 11 21s11-12.7 11-21C22 4.9 17.1 0 11 0z"' +
                    ' fill="' + c + '" stroke="white" stroke-width="1.5"/>' +
                    '<circle cx="11" cy="11" r="4.5" fill="white" opacity="0.75"/></svg>',
                iconSize: [22, 32],
                iconAnchor: [11, 32],
                popupAnchor: [0, -34]
            });
            return L.marker(latlng, {
                icon
            }).bindTooltip(
                '<b>' + feature.properties.name + '</b>' +
                (feature.properties.detalle ? '<br>' + feature.properties.detalle : ''), {
                    direction: 'top',
                    offset: [0, -30]
                }
            );
        },
        function1: function(feature, latlng, index, ctx) {
            const count = feature.properties.point_count;
            const c = (ctx.props.hideout && ctx.props.hideout.color) ? ctx.props.hideout.color : '#3388ff';
            const label = count > 9 ? '+' + count : String(count);
            const icon = L.divIcon({
                className: '',
                html: '<div style="background:' + c + ';color:white;border-radius:50%;width:32px;' +
                    'height:32px;display:flex;align-items:center;justify-content:center;' +
                    'font-weight:700;font-size:12px;border:2px solid white;' +
                    'box-shadow:0 2px 6px rgba(0,0,0,.3)">' + label + '</div>',
                iconSize: [32, 32],
                iconAnchor: [16, 16]
            });
            return L.marker(latlng, {
                icon
            });
        }
    }
});
