from video_harness.blender_renderer.flight_path import flight_distance, flight_speed


def test_camera_recedes_continuously_accelerates_and_arrives_gently():
    samples = [flight_distance(i / 100) for i in range(101)]
    assert samples[0] == 24
    assert samples[-1] == 2400
    assert all(a <= b for a, b in zip(samples, samples[1:]))
    assert flight_speed(.5) > 30 * flight_speed(.1)
    assert flight_speed(.99) < flight_speed(.5) / 30
    assert flight_distance(.22) < 50


def test_timeline_endpoints_clamp_without_a_jump():
    assert flight_distance(-1) == flight_distance(0)
    assert flight_distance(2) == flight_distance(1)
    for p in [.23, .78]:
        assert abs(flight_distance(p + 1e-6) - flight_distance(p - 1e-6)) < .1


def test_opening_fades_only_text_before_the_continuous_pullback():
    from video_harness.blender_renderer.opening_motion import opening_camera_z, opening_text_opacity
    assert opening_text_opacity(7.5) == 1
    assert 0 < opening_text_opacity(8.2) < 1
    assert opening_text_opacity(267 / 30) == 0
    assert opening_camera_z(267 / 30) == flight_distance(0)
    assert opening_camera_z(0) < opening_camera_z(7)


def test_rapid_pullback_arrives_earlier_with_twice_the_peak_speed():
    values=[flight_distance(i/1000,'rapid') for i in range(1001)]
    assert values[0] == flight_distance(0) == 24
    assert values[-1] == flight_distance(1) == 2400
    assert all(a <= b for a,b in zip(values,values[1:]))
    assert max(flight_speed(i/1000,'rapid') for i in range(1001)) > 1.85 * max(flight_speed(i/1000) for i in range(1001))
    assert flight_distance(.39,'rapid') == 2350
    assert flight_distance(.68,'rapid') == 2400
    for p in [.10,.39,.68]:
        assert abs(flight_distance(p+1e-6,'rapid')-flight_distance(p-1e-6,'rapid')) < .1
