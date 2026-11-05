# Starlink API capability report

UTC start: 2026-10-22T16:43:41.433429+00:00
Host OS: Linux; grpcurl runtime: Docker

Read-only, unauthenticated probes. No router configuration changes.
Response values, identifiers, hostnames, IPs, MACs and raw errors are withheld.

Important: schema presence is not runtime support. Empty/omitted fields do not prove absence.
This is a snapshot capability check, not a 24/48-hour traffic capture.

## Router

TCP reachable from this host: yes. This alone does not confirm API access.
Reflection listing: RPC_OR_DESCRIPTION_OK
Schema inspection capped at 70 types; additional types remain unexamined.

### Reflected field definitions

Only field names/types below; no personal response values.

```text
SpaceX.API.Device.Request
  uint64 id = 1
  string target_id = 13
  uint64 epoch_id = 14
  .SpaceX.API.Device.SignedData signed_request = 15
  .SpaceX.API.Device.RebootRequest reboot = 1001
  .SpaceX.API.Device.SpeedTestRequest speed_test = 1003
  .SpaceX.API.Device.GetStatusRequest get_status = 1004
  .SpaceX.API.Device.AuthenticateRequest authenticate = 1005
  .SpaceX.API.Device.GetNextIdRequest get_next_id = 1006
  .SpaceX.API.Device.GetHistoryRequest get_history = 1007
  .SpaceX.API.Device.GetDeviceInfoRequest get_device_info = 1008
  .SpaceX.API.Device.GetPingRequest get_ping = 1009
  .SpaceX.API.Device.SetTrustedKeysRequest set_trusted_keys = 1010
  .SpaceX.API.Device.FactoryResetRequest factory_reset = 1011
  .SpaceX.API.Device.GetLogRequest get_log = 1012
  .SpaceX.API.Device.SetSkuRequest set_sku = 1013
  .SpaceX.API.Device.UpdateRequest update = 1014
  .SpaceX.API.Device.GetNetworkInterfacesRequest get_network_interfaces = 1015
  .SpaceX.API.Device.PingHostRequest ping_host = 1016
  .SpaceX.API.Device.GetLocationRequest get_location = 1017
  .SpaceX.API.Device.GetHeapDumpRequest get_heap_dump = 1019
  .SpaceX.API.Device.RestartControlRequest restart_control = 1020
  .SpaceX.API.Device.FuseRequest fuse = 1021
  .SpaceX.API.Device.GetPersistentStatsRequest get_persistent_stats = 1022
  .SpaceX.API.Device.GetConnectionsRequest get_connections = 1023
  .SpaceX.API.Device.StartSpeedtestRequest start_speedtest = 1027
  .SpaceX.API.Device.GetSpeedtestStatusRequest get_speedtest_status = 1028
  .SpaceX.API.Device.ReportClientSpeedtestRequest report_client_speedtest = 1029
  .SpaceX.API.Device.InitiateRemoteSshRequest initiate_remote_ssh = 1030
  .SpaceX.API.Device.SelfTestRequest self_test = 1031
  .SpaceX.API.Device.SetTestModeRequest set_test_mode = 1032
  .SpaceX.API.Device.SoftwareUpdateRequest software_update = 1033
  .SpaceX.API.Device.EnableDebugTelemRequest enable_debug_telem = 1034
  .SpaceX.API.Device.IQCaptureRequest iq_capture = 1035
  .SpaceX.API.Device.GetRadioStatsRequest get_radio_stats = 1036
  .SpaceX.API.Device.GetTimeRequest time = 1037
  .SpaceX.API.Device.RunIperfServerRequest run_iperf_server = 1038
  .SpaceX.API.Device.TcpConnectivityTestRequest tcp_connectivity_test = 1039
  .SpaceX.API.Device.UdpConnectivityTestRequest udp_connectivity_test = 1040
  .SpaceX.API.Device.GetGoroutineStackTracesRequest get_goroutine_stack_traces = 1041
  .SpaceX.API.Device.SignedData sensitive_request = 1078
  .SpaceX.API.Device.DishStowRequest dish_stow = 2002
  .SpaceX.API.Device.DishGetContextRequest dish_get_context = 2003
  .SpaceX.API.Device.DishSetEmcRequest dish_set_emc = 2007
  .SpaceX.API.Device.DishGetObstructionMapRequest dish_get_obstruction_map = 2008
  .SpaceX.API.Device.DishGetEmcRequest dish_get_emc = 2009
  .SpaceX.API.Device.DishSetConfigRequest dish_set_config = 2010
  .SpaceX.API.Device.DishGetConfigRequest dish_get_config = 2011
  .SpaceX.API.Device.DishPowerSaveRequest dish_power_save = 2013
  .SpaceX.API.Device.DishInhibitGpsRequest dish_inhibit_gps = 2014
  .SpaceX.API.Device.DishGetDataRequest dish_get_data = 2015
  .SpaceX.API.Device.DishClearObstructionMapRequest dish_clear_obstruction_map = 2017
  .SpaceX.API.Device.DishSetMaxPowerTestModeRequest dish_set_max_power_test_mode = 2018
  .SpaceX.API.Device.DishActivateRssiScanRequest dish_activate_rssi_scan = 2019
  .SpaceX.API.Device.DishGetRssiScanResultRequest dish_get_rssi_scan_result = 2020
  .SpaceX.API.Device.DishFactoryResetRequest dish_factory_reset = 2021
  .SpaceX.API.Device.ResetButtonRequest reset_button = 2022
  .SpaceX.API.Device.SoftwareUpdateRequest set_per_vehicle_config = 2023
  .SpaceX.API.Device.DishAviationTestRequest dish_aviation_test = 2024
  .SpaceX.API.Device.DishInhibitRfRequest dish_inhibit_rf = 2026
  .SpaceX.API.Device.ZtlmQueryRequest ztlm_query = 2027
  .SpaceX.API.Device.DishStartTestModeServerRequest dish_start_test_mode_server = 2028
  .SpaceX.API.Device.UserReportedIssueRequest user_reported_issue = 2029
  .SpaceX.API.Device.WifiSetConfigRequest wifi_set_config = 3001
  .SpaceX.API.Device.WifiGetClientsRequest wifi_get_clients = 3002
  .SpaceX.API.Device.WifiSetupRequest wifi_setup = 3003
  .SpaceX.API.Device.WifiGetPingMetricsRequest wifi_get_ping_metrics = 3007
  .SpaceX.API.Device.WifiGetConfigRequest wifi_get_config = 3009
  .SpaceX.API.Device.WifiSetMeshDeviceTrustRequest wifi_set_mesh_device_trust = 3012
  .SpaceX.API.Device.WifiSetMeshConfigRequest wifi_set_mesh_config = 3013
  .SpaceX.API.Device.WifiGetClientHistoryRequest wifi_get_client_history = 3015
  .SpaceX.API.Device.WifiSetAviationConformedRequest wifi_set_aviation_conformed = 3016
  .SpaceX.API.Device.WifiSetClientGivenNameRequest wifi_set_client_given_name = 3017
  .SpaceX.API.Device.WifiSelfTestRequest wifi_self_test = 3018
  .SpaceX.API.Device.WifiCalibrationModeRequest wifi_calibration_mode = 3019
  .SpaceX.API.Device.WifiGuestInfoRequest wifi_guest_info = 3020
  .SpaceX.API.Device.WifiRfTestRequest wifi_rf_test = 3021
  .SpaceX.API.Device.WifiGetFirewallRequest wifi_get_firewall = 3024
  .SpaceX.API.Device.WifiTogglePoeNegotiationRequest wifi_toggle_poe_negotiation = 3025
  .SpaceX.API.Device.WifiFactoryTestCommandRequest wifi_factory_test_command = 3026
  .SpaceX.API.Device.WifiStartLocalTelemProxyRequest wifi_start_local_telem_proxy = 3027
  .SpaceX.API.Device.WifiRunSelfTestRequest wifi_run_self_test = 3028
  .SpaceX.API.Device.WifiBackhaulStatsRequest wifi_backhaul_stats = 3029
  .SpaceX.API.Device.WifiToggleUmbilicalModeRequest wifi_toggle_umbilical_mode = 3030
  .SpaceX.API.Device.WifiClientSandboxRequest wifi_client_sandbox = 3031
  .SpaceX.API.Device.WifiRunDebugNetsysRequest wifi_run_debug_netsys = 3032
  .SpaceX.API.Device.WifiResetEthPhyRequest wifi_reset_eth_phy = 3033
  .SpaceX.API.Device.WifiFlushHardwareNatRequest wifi_flush_hardware_nat = 3034
  .SpaceX.API.Device.WifiWriteCalibrationRequest wifi_write_calibration = 3035
  .SpaceX.API.Device.WifiStartTracerouteRequest wifi_start_traceroute = 3036
  .SpaceX.API.Device.WifiGetTracerouteStatusRequest wifi_get_traceroute_status = 3037
  .SpaceX.API.Device.WifiGetChannelsRequest wifi_get_channels = 3038
  .SpaceX.API.Device.TransceiverIFLoopbackTestRequest transceiver_if_loopback_test = 4001
  .SpaceX.API.Device.TransceiverGetStatusRequest transceiver_get_status = 4003
  .SpaceX.API.Device.TransceiverGetTelemetryRequest transceiver_get_telemetry = 4004
  .SpaceX.API.Device.Services.Unlock.StartUnlockRequest start_unlock = 5000
  .SpaceX.API.Device.Services.Unlock.FinishUnlockRequest finish_unlock = 5001
  .SpaceX.API.Device.GetDiagnosticsRequest get_diagnostics = 6000
  .SpaceX.API.Device.GetGnssMeasurementRequest get_gnss_measurement = 7000
  .SpaceX.API.Device.ToggleModeRequest toggle_mode = 7001
  .SpaceX.API.Device.GetToggleModeRequest toggle_mode_status = 7002
SpaceX.API.Device.Response
  uint64 id = 1
  .SpaceX.API.Status.Status status = 2
  uint64 api_version = 3
  .SpaceX.API.Device.RebootResponse reboot = 1001
  .SpaceX.API.Device.SpeedTestResponse speed_test = 1003
  .SpaceX.API.Device.GetDeviceInfoResponse get_device_info = 1004
  .SpaceX.API.Device.GetNextIdResponse get_next_id = 1006
  .SpaceX.API.Device.GetPingResponse get_ping = 1009
  .SpaceX.API.Device.SetTrustedKeysResponse set_trusted_keys = 1010
  .SpaceX.API.Device.FactoryResetResponse factory_reset = 1011
  .SpaceX.API.Device.GetLogResponse get_log = 1012
  .SpaceX.API.Device.SetSkuResponse set_sku = 1013
  .SpaceX.API.Device.UpdateResponse update = 1014
  .SpaceX.API.Device.GetNetworkInterfacesResponse get_network_interfaces = 1015
  .SpaceX.API.Device.PingHostResponse ping_host = 1016
  .SpaceX.API.Device.GetLocationResponse get_location = 1017
  .SpaceX.API.Device.GetHeapDumpResponse get_heap_dump = 1019
  .SpaceX.API.Device.RestartControlResponse restart_control = 1020
  .SpaceX.API.Device.FuseResponse fuse = 1021
  .SpaceX.API.Device.GetConnectionsResponse get_connections = 1023
  .SpaceX.API.Device.StartSpeedtestResponse start_speedtest = 1027
  .SpaceX.API.Device.GetSpeedtestStatusResponse get_speedtest_status = 1028
  .SpaceX.API.Device.ReportClientSpeedtestResponse report_client_speedtest = 1029
  .SpaceX.API.Device.InitiateRemoteSshResponse initiate_remote_ssh = 1030
  .SpaceX.API.Device.SelfTestResponse self_test = 1031
  .SpaceX.API.Device.SetTestModeResponse set_test_mode = 1032
  .SpaceX.API.Device.SoftwareUpdateResponse software_update = 1033
  .SpaceX.API.Device.EnableDebugTelemResponse enable_debug_telem = 1034
  .SpaceX.API.Device.GetRadioStatsResponse get_radio_stats = 1035
  .SpaceX.API.Device.GetTimeResponse time = 1037
  .SpaceX.API.Device.RunIperfServerResponse run_iperf_server = 1038
  .SpaceX.API.Device.GetGoroutineStackTracesResponse get_goroutine_stack_traces = 1041
  .SpaceX.API.Device.DishStowResponse dish_stow = 2002
  .SpaceX.API.Device.DishGetContextResponse dish_get_context = 2003
  .SpaceX.API.Device.DishGetStatusResponse dish_get_status = 2004
  .SpaceX.API.Device.DishAuthenticateResponse dish_authenticate = 2005
  .SpaceX.API.Device.DishGetHistoryResponse dish_get_history = 2006
  .SpaceX.API.Device.DishSetEmcResponse dish_set_emc = 2007
  .SpaceX.API.Device.DishGetObstructionMapResponse dish_get_obstruction_map = 2008
  .SpaceX.API.Device.DishGetEmcResponse dish_get_emc = 2009
  .SpaceX.API.Device.DishSetConfigResponse dish_set_config = 2010
  .SpaceX.API.Device.DishGetConfigResponse dish_get_config = 2011
  .SpaceX.API.Device.DishInhibitGpsResponse dish_inhibit_gps = 2013
  .SpaceX.API.Device.DishClearObstructionMapResponse dish_clear_obstruction_map = 2015
  .SpaceX.API.Device.DishSetMaxPowerTestModeResponse dish_set_max_power_test_mode = 2018
  .SpaceX.API.Device.DishActivateRssiScanResponse dish_activate_rssi_scan = 2019
  .SpaceX.API.Device.DishGetRssiScanResultResponse dish_get_rssi_scan_result = 2020
  .SpaceX.API.Device.DishFactoryResetResponse dish_factory_reset = 2021
  .SpaceX.API.Device.ResetButtonResponse reset_button = 2022
  .SpaceX.API.Device.SetPerVehicleConfigResponse set_per_vehicle_config = 2023
  .SpaceX.API.Device.DishAviationTestResponse dish_aviation_test = 2024
  .SpaceX.API.Device.DishInhibitRfResponse dish_inhibit_rf = 2026
  .SpaceX.API.Device.ZtlmQueryResponse ztlm_query = 2027
  .SpaceX.API.Device.DishStartTestModeServerResponse dish_start_test_mode_server = 2028
  .SpaceX.API.Device.UserReportedIssueResponse user_reported_issue = 2029
  .SpaceX.API.Device.WifiSetConfigResponse wifi_set_config = 3001
  .SpaceX.API.Device.WifiGetClientsResponse wifi_get_clients = 3002
  .SpaceX.API.Device.WifiSetupResponse wifi_setup = 3003
  .SpaceX.API.Device.WifiGetStatusResponse wifi_get_status = 3004
  .SpaceX.API.Device.WifiAuthenticateResponse wifi_authenticate = 3005
  .SpaceX.API.Device.WifiGetHistoryResponse wifi_get_history = 3006
  .SpaceX.API.Device.WifiGetPingMetricsResponse wifi_get_ping_metrics = 3007
  .SpaceX.API.Device.WifiGetConfigResponse wifi_get_config = 3009
  .SpaceX.API.Device.WifiSetMeshDeviceTrustResponse wifi_set_mesh_device_trust = 3012
  .SpaceX.API.Device.WifiSetMeshConfigResponse wifi_set_mesh_config = 3013
  .SpaceX.API.Device.WifiGetClientHistoryResponse wifi_get_client_history = 3015
  .SpaceX.API.Device.WifiSelfTestResponse wifi_self_test = 3016
  .SpaceX.API.Device.WifiGuestInfoResponse wifi_guest_info = 3020
  .SpaceX.API.Device.WifiRfTestResponse wifi_rf_test = 3021
  .SpaceX.API.Device.WifiGetPersistentStatsResponse wifi_get_persistent_stats = 3022
  .SpaceX.API.Device.WifiGetFirewallResponse wifi_get_firewall = 3024
  .SpaceX.API.Device.WifiFactoryTestCommandResponse wifi_factory_test_command = 3025
  .SpaceX.API.Device.WifiBackhaulStatsResponse wifi_backhaul_stats = 3026
  .SpaceX.API.Device.WifiClientSandboxResponse wifi_client_sandbox = 3027
  .SpaceX.API.Device.WifiUpdateResponse wifi_update = 3028
  .SpaceX.API.Device.WifiRunDebugNetsysResponse wifi_run_debug_netsys = 3029
  .SpaceX.API.Device.WifiResetEthPhyResponse wifi_reset_eth_phy = 3030
  .SpaceX.API.Device.WifiFlushHardwareNatResponse wifi_flush_hardware_nat = 3031
  .SpaceX.API.Device.WifiGetTracerouteStatusResponse wifi_get_traceroute_status = 3032
  .SpaceX.API.Device.WifiGetChannelsResponse wifi_get_channels = 3033
  .SpaceX.API.Device.TransceiverIFLoopbackTestResponse transceiver_if_loopback_test = 4001
  .SpaceX.API.Device.TransceiverGetStatusResponse transceiver_get_status = 4003
  .SpaceX.API.Device.TransceiverGetTelemetryResponse transceiver_get_telemetry = 4004
  .SpaceX.API.Device.Services.Unlock.StartUnlockResponse start_unlock = 5000
  .SpaceX.API.Device.Services.Unlock.FinishUnlockResponse finish_unlock = 5001
  .SpaceX.API.Device.WifiGetDiagnosticsResponse wifi_get_diagnostics = 6000
  .SpaceX.API.Device.DishGetDiagnosticsResponse dish_get_diagnostics = 6001
  .SpaceX.API.Device.GetGnssMeasurementResponse get_gnss_measurement = 7000
  .SpaceX.API.Device.ToggleModeResponse toggle_mode = 7001
  .SpaceX.API.Device.GetToggleModeResponse toggle_mode_status = 7002
SpaceX.API.Device.GetDeviceInfoResponse
  .SpaceX.API.Device.DeviceInfo device_info = 1
SpaceX.API.Device.DeviceInfo
  string id = 1
  string hardware_version = 2
  string software_version = 3
  string country_code = 4
  int32 utc_offset_s = 5
  bool software_partitions_equal = 6
  bool is_dev = 7
  int32 bootcount = 8
  int32 anti_rollback_version = 9
  bool is_hitl = 10
  string manufactured_version = 11
  int64 generation_number = 12
  bool dish_cohoused = 13
  int32 board_rev = 14
  string build_id = 15
  .SpaceX.API.Device.HardwareIndex hardware_index = 16
  int32 inactive_anti_rollback_version = 17
  .SpaceX.API.Device.BootInfo boot = 1001
SpaceX.API.Device.GetConnectionsResponse
  map<string, .SpaceX.API.Device.GetConnectionsResponse.ServiceConnection> services = 1
  string address = 1
  int32 seconds_since_success = 2
SpaceX.API.Device.WifiGetStatusResponse
  bool captive_portal_enabled = 1
  .SpaceX.API.Device.DeviceInfo device_info = 3
  .SpaceX.API.Device.DeviceState device_state = 4
  string ipv4_wan_address = 1003
  float ping_drop_rate = 1004
  float ping_latency_ms = 1005
  .SpaceX.API.Device.WifiBandStatus rf_2ghz_status = 1008
  .SpaceX.API.Device.WifiBandStatus rf_5ghz_status = 1009
  .SpaceX.API.Device.WifiAlerts alerts = 1010
  bool is_aviation = 1011
  float dish_ping_drop_rate = 1012
  float dish_ping_latency_ms = 1013
  float pop_ping_drop_rate = 1014
  float pop_ping_latency_ms = 1015
  bool is_aviation_conformed = 1016
  string ipv6_wan_addresses = 1017
  float dish_ping_drop_rate_5m = 1018
  .SpaceX.API.Device.DhcpServer dhcp_servers = 1019
  float pop_ping_drop_rate_5m = 1020
  float ping_drop_rate_5m = 1021
  .SpaceX.API.Device.PoeStats poe_stats = 1022
  string dish_id = 1023
  int64 utc_ns = 1024
  .SpaceX.API.Device.WifiSoftwareUpdateStats software_update_stats = 1025
  .SpaceX.API.Device.WifiSetupRequirement setup_requirement = 1026
  float pop_ipv6_ping_drop_rate = 1027
  float pop_ipv6_ping_drop_rate_5m = 1028
  float pop_ipv6_ping_latency_ms = 1029
  float secs_since_last_public_ipv4_change = 1030
  .SpaceX.API.Satellites.Network.UtDisablementCode dish_disablement_code = 1031
  bool using_individualized_calibration = 1032
  .SpaceX.API.Device.CalibrationPartitionsState calibration_partitions_state = 1033
  uint32 hops_from_controller = 1034
  bool no_wan_link = 1035
  string public_ipv4 = 1036
  .SpaceX.API.Device.UsbDevice usb_devices = 1037
  .SpaceX.API.Device.WifiConfig config = 2000
  .SpaceX.API.Device.WifiClient clients = 3000
  bool has_client_index = 3001
  int32 client_index = 3002
  .SpaceX.API.Device.RadiusStatsMap radius_stats = 3003
SpaceX.API.Device.WifiGetClientsResponse
  .SpaceX.API.Device.WifiClient clients = 1
  bool has_client_index = 2
  int32 client_index = 3
SpaceX.API.Device.WifiClient
  string name = 1
  string mac_address = 2
  string ip_address = 3
  float signal_strength = 4
  .SpaceX.API.Device.WifiClient.RxStats rx_stats = 5
  .SpaceX.API.Device.WifiClient.TxStats tx_stats = 6
  uint32 associated_time_s = 7
  string mode_str = 8
  .SpaceX.API.Device.WifiClient.Interface iface = 9
  float snr = 10
  int32 psmode = 11
  uint32 channel_width = 12
  string upstream_mac_address = 13
  .SpaceX.API.Device.WifiClient.Role role = 14
  string device_id = 15
  uint32 swq_checks = 16
  uint32 swq_checks_non_empty = 17
  uint32 mib_steer_state = 18
  uint32 mib_steer_method = 19
  uint32 btm_requests = 20
  uint32 btm_requests_success = 21
  string domain = 22
  bool dot11v_support = 23
  string iface_name = 26
  uint32 steer_req_success_last_1h = 27
  uint32 steer_req_fail_last_1h = 28
  uint32 steer_req_fail_and_dissoc_last_1h = 29
  uint32 steer_state = 30
  string given_name = 31
  uint32 hops_from_controller = 32
  float est_tx_rate_mbps_from_controller = 33
  float est_rx_rate_mbps_from_controller = 34
  string hardware_version = 37
  string software_version = 38
  uint32 api_version = 39
  .SpaceX.API.Device.WifiClient.PingMetrics ping_metrics = 40
  string ipv6_addresses = 41
  bool blocked = 42
  uint32 client_id = 43
  .SpaceX.API.Device.WifiClient.FqcodelInfo fqcodel_info = 44
  uint32 no_data_idle_s = 45
  bool dhcp_lease_active = 46
  bool dhcp_lease_renewed = 47
  float seconds_until_dhcp_lease_expires = 48
  bool dhcp_lease_found = 49
  .SpaceX.API.Device.WifiClient.Alerts alerts = 52
  string captive_client_id = 53
  uint32 upload_mb = 54
  uint32 download_mb = 55
  .SpaceX.API.Device.WifiClient.CaptiveState captive_state = 56
  .SpaceX.API.Device.WifiClient.SandboxState sandbox_state = 57
  bool active = 58
  uint32 power_save_mode_count = 59
  bool rx_stats_valid = 60
  bool tx_stats_valid = 61
  uint64 power_save_mode_duration_ms = 62
  int32 power_save_mode = 63
  .SpaceX.API.Device.WifiClient.Link links = 70
  bool using_mlo = 71
  bool throughput_limited = 1
  uint64 enqs_hi_prio = 1
  uint64 enqs_fqcodel = 2
  uint64 enqs_new = 3
  uint64 enqs_old = 4
  uint64 enqs_dropped = 5
  uint64 deqs_new = 6
  uint64 deqs_old = 7
  uint64 deqs_flow_new = 8
  uint64 deqs_flow_old_deficit = 9
  uint64 deqs_flow_old_starvation = 10
  uint64 deqs_dropped = 11
  string link_address = 1
  .SpaceX.API.Device.WifiClient.Interface band = 2
  float signal_strength = 3
  .SpaceX.API.Device.WifiClient.RxStats rx_stats = 4
  .SpaceX.API.Device.WifiClient.TxStats tx_stats = 5
  float snr = 6
  bool in_unhappy_hour_2s = 1
  bool in_unhappy_hour_5s = 2
  float drop_rate_5m = 3
  float latency_5m = 4
  uint64 bytes = 1
  uint64 count_errors = 2
  int32 nss = 3
  uint32 mcs = 5
  uint32 bandwidth = 6
  uint32 guard_ns = 7
  uint32 rate_mbps = 8
  float airtime_fraction_last_1s = 9
  uint32 sampled_packets = 10
  uint32 sampled_packets_retried = 11
  uint32 sampled_packets_dropped = 12
  uint32 phy_mode = 13
  float rate_mbps_last_30s = 14
  float rate_mbps_last_15s = 15
  float rate_mbps_last_1m_avg = 16
  float throughput_mbps_last_1m_avg = 17
  float throughput_mbps_last_15s_avg = 18
  uint32 wmm_voice_bytes = 20
  uint32 wmm_video_bytes = 21
  uint32 wmm_best_effort_bytes = 22
  uint32 wmm_background_bytes = 23
  uint32 wmm_voice_bytes_failed = 24
  uint32 wmm_video_bytes_failed = 25
  uint32 wmm_best_effort_bytes_failed = 26
  uint32 wmm_background_bytes_failed = 27
  uint64 bytes = 1
  uint64 success_bytes = 2
  int32 nss = 3
  uint32 mcs = 5
  uint32 bandwidth = 6
  uint32 guard_ns = 7
  uint32 rate_mbps = 8
  float airtime_fraction_last_1s = 9
  uint32 phy_mode = 10
  float rate_mbps_last_30s = 11
  float rate_mbps_last_15s = 12
  float throughput_mbps_last_15s_avg = 13
  uint32 wmm_voice_bytes = 20
  uint32 wmm_video_bytes = 21
  uint32 wmm_best_effort_bytes = 22
  uint32 wmm_background_bytes = 23
SpaceX.API.Device.WifiGetClientHistoryRequest
  string mac_address = 1
  uint32 client_id = 2
SpaceX.API.Device.WifiGetClientHistoryResponse
  uint64 current = 1
  float tx_throughput_mbps = 2
  float rx_throughput_mbps = 3
  .SpaceX.API.Device.WifiGetClientHistoryResponse.WifiLimitedReason throughput_limited = 4
  float rx_rate_mbps = 5
  bytes rssi = 6
SpaceX.API.Device.WifiGetHistoryResponse
  uint64 current = 1
  uint64 current_index_15s = 2
  float ping_drop_rate = 1001
  float ping_latency_ms = 1002
  float pop_ipv4_ping_drop_rate_last_15s = 1003
  float pop_ipv6_ping_drop_rate_last_15s = 1004
  float google_ipv4_ping_drop_rate_last_15s = 1005
  float google_ipv6_ping_drop_rate_last_15s = 1006
  float cloudflare_ipv4_ping_drop_rate_last_15s = 1007
  float cloudflare_ipv6_ping_drop_rate_last_15s = 1008
  map<string, .SpaceX.API.Device.WifiGetHistoryResponse.DnsResolverHistory> dns_resolver_drop_rate = 1009
  .SpaceX.API.Device.EventLog event_log = 1010
  float drop_rate_last_15s = 2
SpaceX.API.Device.GetConnectionsRequest
SpaceX.API.Device.HardwareIndex
SpaceX.API.Device.BootInfo
  map<int32, int32> count_by_reason = 1
  .SpaceX.API.Device.BootReason last_reason = 2
  int32 last_count = 3
  map<int32, int32> count_by_reason_delta = 4
  bool crash_boot = 5
  int32 crash_boot_count = 6
  string even_side_software_version = 7
  string odd_side_software_version = 8
  int32 api_version_odd_side = 9
  int32 api_version_even_side = 10
SpaceX.API.Device.DeviceState
  uint64 uptime_s = 1
SpaceX.API.Device.WifiBandStatus
  float chan_busy_time_fraction = 1
  float tx_air_time_fraction = 2
  float rx_air_time_fraction = 3
  float obss_air_time_fraction = 4
  float edcca_air_time_fraction = 5
SpaceX.API.Device.WifiAlerts
  bool thermal_throttle = 1
  bool install_pending = 2
  bool freshly_fused = 3
  bool lan_eth_slow_link_10 = 4
  bool lan_eth_slow_link_100 = 5
  bool wan_eth_poor_connection = 10
  bool mesh_topology_changing_often = 11
  bool mesh_unreliable_backhaul = 12
  bool radius_missing_process = 13
  bool eth_switch_error = 14
  bool poe_on_dish_unreachable = 15
  bool poe_fuse_blown = 16
  bool poe_router_overcurrent = 17
  bool poe_off_current_nominal = 18
  bool poe_vin_overvoltage = 19
  bool poe_vin_undervoltage = 20
  bool high_cable_ping_drop_rate = 21
  bool sandbox_disabled = 22
  bool only_overflight_blocked = 23
  bool offline_networks_disabled = 24
  bool wired_mesh_not_using_wan_iface = 25
SpaceX.API.Device.DhcpServer
  string domain = 1
  string subnet = 2
  .SpaceX.API.Device.DhcpLease leases = 3
  bool ip_exhausted = 4
SpaceX.API.Device.PoeStats
  .SpaceX.API.Device.PoeState poe_state = 1
  float poe_power = 2
  uint32 poe_faults_fast_overcurrent = 3
  uint32 poe_faults_slow_overcurrent = 4
  uint32 poe_faults_overvoltage = 5
  uint32 poe_faults_undervoltage = 6
  float vsns_vin = 7
SpaceX.API.Device.WifiSoftwareUpdateStats
  .SpaceX.API.Device.WifiSoftwareUpdateState state = 1
  float software_download_progress = 2
  float seconds_since_get_target_versions = 3
  string running_version = 4
  string version_in_progress = 5
SpaceX.API.Device.WifiSetupRequirement
  .SpaceX.API.Device.WifiSetupRequirementState state = 1
  uint64 pause_countdown_seconds = 2
SpaceX.API.Device.CalibrationPartitionsState
SpaceX.API.Device.UsbDevice
  uint32 bus = 1
  uint32 parent = 2
  uint32 port = 3
  uint32 dev_num = 4
  uint32 speed = 5
  string vendor = 6
  string prod_id = 7
  string rev = 8
  string manufacturer = 9
  string product = 10
  string serial = 11
  string max_power = 12
  bool active = 13
SpaceX.API.Device.WifiConfig
  string country_code = 3
  bool setup_complete = 7
  uint32 version = 9
  string mac_wan = 12
  string mac_lan = 13
  uint32 channel_2ghz = 19
  uint32 channel_5ghz = 20
  .SpaceX.API.Device.PublicKey dynamic_keys = 22
  bool is_repeater = 23
  int32 boot_count = 26
  string nameservers = 30
  bool bypass_mode = 31
  map<string, .SpaceX.API.Device.MeshConfig> mesh_configs = 33
  bool apply_dynamic_keys = 39
  bool dfs_enabled = 42
  uint64 incarnation = 43
  .SpaceX.API.Device.WifiConfig.WirelessMode wireless_mode_2ghz = 44
  .SpaceX.API.Device.WifiConfig.WirelessMode wireless_mode_5ghz = 45
  .SpaceX.API.Device.WifiConfig.HTBandwidth ht_bandwidth_2ghz = 46
  .SpaceX.API.Device.WifiConfig.HTBandwidth ht_bandwidth_5ghz = 47
  .SpaceX.API.Device.WifiConfig.VHTBandwidth vht_bandwidth = 48
  bool is_aviation = 49
  bool secure_dns = 50
  bool ap_mode = 51
  bool disable_mesh_onboarding = 52
  bool pin_country_code = 53
  bool custom_power_table = 54
  bool disable_automated_speedtests = 56
  uint32 channel_5ghz_high = 57
  .SpaceX.API.Device.WifiConfig.WirelessMode wireless_mode_5ghz_high = 58
  .SpaceX.API.Device.WifiConfig.HTBandwidth ht_bandwidth_5ghz_high = 59
  .SpaceX.API.Device.WifiConfig.VHTBandwidth vht_bandwidth_5ghz_high = 60
  bool enable_umbilical_vlan = 61
  .SpaceX.API.Device.ClientName client_names = 62
  bool outdoor_mode = 63
  bool disable_2ghz = 64
  bool disable_5ghz = 65
  bool disable_5ghz_high = 66
  bool disable_x_mesh_backhaul = 67
  string golden_bssid = 68
  .SpaceX.API.Device.IfaceType golden_iface_type = 69
  .SpaceX.API.Device.TxPowerLevel tx_power_level_2ghz = 70
  .SpaceX.API.Device.TxPowerLevel tx_power_level_5ghz = 71
  .SpaceX.API.Device.TxPowerLevel tx_power_level_5ghz_high = 72
  bool disable_pending_update_reboot = 73
  .SpaceX.API.Device.ClientConfig client_configs = 74
  bool disable_set_wifi_config_from_controller = 75
  bytes client_key = 76
  int32 wan_host_dscp_mark = 77
  uint32 tag = 78
  bool debug_pop_pings = 79
  bool client_tester = 80
  uint32 asset_class = 81
  bool debug_pings = 94
  bool disable_band_steering = 95
  bool apply_setup_complete = 1010
  bool apply_channel_2ghz = 1013
  bool apply_channel_5ghz = 1014
  bool apply_channel_5ghz_high = 1016
  bool apply_is_repeater = 1031
  bool apply_mesh_configs = 1033
  bool apply_nameservers = 1054
  bool apply_bypass_mode = 1055
  bool apply_dfs_enabled = 1058
  bool apply_wireless_mode_2ghz = 1059
  bool apply_wireless_mode_5ghz = 1060
  bool apply_ht_bandwidth_2ghz = 1061
  bool apply_ht_bandwidth_5ghz = 1062
  bool apply_vht_bandwidth = 1063
  bool apply_is_aviation = 1064
  bool apply_secure_dns = 1065
  bool apply_ap_mode = 1066
  bool apply_disable_mesh_onboarding = 1067
  bool apply_disable_automated_speedtests = 1069
  bool apply_wireless_mode_5ghz_high = 1070
  bool apply_ht_bandwidth_5ghz_high = 1071
  bool apply_vht_bandwidth_5ghz_high = 1072
  bool apply_enable_umbilical_vlan = 1073
  bool apply_client_names = 1074
  bool apply_outdoor_mode = 1075
  bool apply_disable_2ghz = 1076
  bool apply_disable_5ghz = 1077
  bool apply_disable_5ghz_high = 1078
  bool apply_disable_x_mesh_backhaul = 1079
  bool apply_golden_bssid = 1080
  bool apply_golden_iface_type = 1081
  bool apply_tx_power_level_2ghz = 1082
  bool apply_tx_power_level_5ghz = 1083
  bool apply_tx_power_level_5ghz_high = 1084
  bool apply_country_code = 1085
  bool apply_pin_country_code = 1086
  bool apply_custom_power_table = 1087
  bool apply_disable_pending_update_reboot = 1088
  bool apply_client_configs = 1089
  bool apply_disable_set_wifi_config_from_controller = 1090
  bool apply_client_key = 1091
  bool apply_wan_traffic_control = 1092
  bool apply_wan_host_dscp_mark = 1093
  bool apply_debug_pop_pings = 1095
  bool apply_client_tester = 1096
  bool disable_wireless_mesh_onboarding = 1097
  bool apply_disable_wireless_mesh_onboarding = 1098
  bool apply_asset_class = 1099
  .SpaceX.API.Device.WifiConfig.Network networks = 1100
  bool apply_networks = 1101
  bool apply_debug_pings = 1106
  bool apply_http_server = 1107
  .SpaceX.API.Device.HttpServer http_server = 1108
  bool apply_disable_band_steering = 1109
  string only_overflight_countries = 1110
  bool apply_only_overflight_countries = 1111
  .SpaceX.API.Device.WifiConfig.UnbridgedEthPort unbridged_eth_ports = 1112
  bool apply_unbridged_eth_ports = 1113
  bool only_overflight_countries_using_default = 1114
  bool disable_sandbox_fail_open = 1115
  bool apply_disable_sandbox_fail_open = 1116
  bool custom_dns_disabled = 1117
  bool apply_custom_dns_disabled = 1118
  bool foreflight_enabled = 1119
  bool apply_foreflight_enabled = 1120
  .SpaceX.API.Device.WifiConfig.MultiTenantRole multi_tenant_role = 1121
  bool apply_multi_tenant_role = 1122
  string tenant_router_ids = 1123
  bool apply_tenant_router_ids = 1124
  .SpaceX.API.Device.BootInfo boot = 3001
  map<string, .SpaceX.API.Device.MeshConfig> mesh_configs_updates = 3033
  .SpaceX.API.Device.NoTrafficControl wan_no_traffic_control = 4001
  .SpaceX.API.Device.AckSuppression wan_ack_suppression = 4002
  .SpaceX.API.Device.CakeRateLimit wan_cake_rate_limit = 4003
  string bssid = 1003
  string ssid = 1005
  .SpaceX.API.Device.WifiConfig.Band band = 1011
  bool disable = 1013
  bool hidden = 1015
  string iface_name = 1017
  .SpaceX.API.Device.AuthOpen auth_open = 2001
  .SpaceX.API.Device.AuthWpa2 auth_wpa2 = 2002
  .SpaceX.API.Device.AuthWpa3 auth_wpa3 = 2003
  .SpaceX.API.Device.AuthWpa2Wpa3 auth_wpa2_wpa3 = 2004
  .SpaceX.API.Device.AuthRadius auth_radius = 2005
  .SpaceX.API.Device.AuthOpenEncrypted auth_open_encrypted = 2006
  .SpaceX.API.Device.AuthOnboardRadius auth_onboard_radius = 2007
  string domains = 1000
  string server_addresses = 1001
  string domains = 1000
  string addresses = 1001
  string ipv4 = 1003
  .SpaceX.API.Device.WifiConfig.BasicServiceSet basic_service_sets = 1007
  bool client_isolation = 1008
  bool guest = 1009
  string landing = 1010
  string domain = 1011
  uint32 dhcpv4_start = 1012
  bool internal = 1013
  uint32 vlan = 1014
  bool dhcp_disabled = 1015
  uint32 dhcpv4_lease_duration_s = 1016
  bool landing_page_v2 = 1017
  bool sandbox_enabled = 1020
  string sandbox_domain_allow_list = 1022
  uint32 sandbox_id = 1023
  .SpaceX.API.Device.CaptivePortal captive_portal = 1024
  uint32 dhcpv4_end = 1025
  uint32 network_groups = 1026
  .SpaceX.API.Device.WifiConfig.DnsStaticEntry dns_static_entries = 1027
  .SpaceX.API.Device.WifiConfig.DnsForwardRule dns_forward_rules = 1028
  bool disable_when_offline_old = 1029
  .SpaceX.API.Device.WifiConfig.StaticRoute static_routes = 1030
  bool disable_when_offline = 1031
  .SpaceX.API.Device.TlsConfig onboard_radius_tls_config_old = 1032
  .SpaceX.API.Device.TlsConfig onboard_radius_tls_config = 1033
  bool dns_disabled = 1034
  bool get_lease_dhcp = 1035
  bool default_route_disabled = 1036
  .SpaceX.API.Device.WifiConfig.Network.GeofenceAction geofence_action = 1038
  string subnet = 1
  string gateway = 2
  uint32 lan_port_index = 1
  string ip = 2
  string gateway = 3
  .SpaceX.API.Device.WifiConfig.UnbridgedEthPort.StaticRoute static_routes = 4
  .SpaceX.API.Device.WanNone wan_none = 5
  .SpaceX.API.Device.WanStarlinkRouterPair wan_starlink_router_pair = 6
  uint32 bridged_network_group_override = 7
  string subnet = 1
  uint32 network_groups = 2
SpaceX.API.Device.RadiusStatsMap
  map<string, .SpaceX.API.Device.RadiusStatsMap.RadiusStats> radius_stats = 1
  string iface_name = 1
  uint32 timeout_count = 2
  uint32 access_request_count = 3
  uint32 access_accept_count = 4
  uint32 access_reject_count = 5
  uint32 access_challenge_count = 6
  uint32 accounting_request_count = 7
  uint32 accounting_response_count = 8
SpaceX.API.Device.WifiClient.RxStats
  uint64 bytes = 1
  uint64 count_errors = 2
  int32 nss = 3
  uint32 mcs = 5
  uint32 bandwidth = 6
  uint32 guard_ns = 7
  uint32 rate_mbps = 8
  float airtime_fraction_last_1s = 9
  uint32 sampled_packets = 10
  uint32 sampled_packets_retried = 11
  uint32 sampled_packets_dropped = 12
  uint32 phy_mode = 13
  float rate_mbps_last_30s = 14
  float rate_mbps_last_15s = 15
  float rate_mbps_last_1m_avg = 16
  float throughput_mbps_last_1m_avg = 17
  float throughput_mbps_last_15s_avg = 18
  uint32 wmm_voice_bytes = 20
  uint32 wmm_video_bytes = 21
  uint32 wmm_best_effort_bytes = 22
  uint32 wmm_background_bytes = 23
  uint32 wmm_voice_bytes_failed = 24
  uint32 wmm_video_bytes_failed = 25
  uint32 wmm_best_effort_bytes_failed = 26
  uint32 wmm_background_bytes_failed = 27
SpaceX.API.Device.WifiClient.TxStats
  uint64 bytes = 1
  uint64 success_bytes = 2
  int32 nss = 3
  uint32 mcs = 5
  uint32 bandwidth = 6
  uint32 guard_ns = 7
  uint32 rate_mbps = 8
  float airtime_fraction_last_1s = 9
  uint32 phy_mode = 10
  float rate_mbps_last_30s = 11
  float rate_mbps_last_15s = 12
  float throughput_mbps_last_15s_avg = 13
  uint32 wmm_voice_bytes = 20
  uint32 wmm_video_bytes = 21
  uint32 wmm_best_effort_bytes = 22
  uint32 wmm_background_bytes = 23
SpaceX.API.Device.WifiClient.Interface
SpaceX.API.Device.WifiClient.Role
SpaceX.API.Device.WifiClient.PingMetrics
  bool in_unhappy_hour_2s = 1
  bool in_unhappy_hour_5s = 2
  float drop_rate_5m = 3
  float latency_5m = 4
SpaceX.API.Device.WifiClient.FqcodelInfo
  uint64 enqs_hi_prio = 1
  uint64 enqs_fqcodel = 2
  uint64 enqs_new = 3
  uint64 enqs_old = 4
  uint64 enqs_dropped = 5
  uint64 deqs_new = 6
  uint64 deqs_old = 7
  uint64 deqs_flow_new = 8
  uint64 deqs_flow_old_deficit = 9
  uint64 deqs_flow_old_starvation = 10
  uint64 deqs_dropped = 11
SpaceX.API.Device.WifiClient.Alerts
  bool throughput_limited = 1
SpaceX.API.Device.WifiClient.CaptiveState
SpaceX.API.Device.WifiClient.SandboxState
SpaceX.API.Device.WifiClient.Link
  string link_address = 1
  .SpaceX.API.Device.WifiClient.Interface band = 2
  float signal_strength = 3
  .SpaceX.API.Device.WifiClient.RxStats rx_stats = 4
  .SpaceX.API.Device.WifiClient.TxStats tx_stats = 5
  float snr = 6
SpaceX.API.Device.WifiGetClientHistoryResponse.WifiLimitedReason
SpaceX.API.Device.EventLog
  .SpaceX.API.Device.UXEvent events = 1
  int64 start_timestamp_ns = 2
  int64 current_timestamp_ns = 3
SpaceX.API.Device.BootReason
SpaceX.API.Device.DhcpLease
  string ip_address = 1
  string mac_address = 2
  string hostname = 3
  string expires_time = 4
  bool active = 5
  uint32 client_id = 6
SpaceX.API.Device.PoeState
SpaceX.API.Device.WifiSoftwareUpdateState
SpaceX.API.Device.WifiSetupRequirementState
SpaceX.API.Device.PublicKey
  string key = 1
  .SpaceX.API.Device.Capability capabilities = 2
  .SpaceX.API.Device.User user = 3
SpaceX.API.Device.WifiConfig.WirelessMode
SpaceX.API.Device.WifiConfig.HTBandwidth
SpaceX.API.Device.WifiConfig.VHTBandwidth
SpaceX.API.Device.ClientName
  string mac_address = 1
  string given_name = 2
SpaceX.API.Device.IfaceType
SpaceX.API.Device.TxPowerLevel
SpaceX.API.Device.ClientConfig
  uint32 client_id = 1
  string mac_address = 2
  string given_name = 3
  .SpaceX.API.Device.WeeklyBlockSchedule weekly_block_schedules = 5
  string group_id = 6
SpaceX.API.Device.WifiConfig.Network
  string ipv4 = 1003
  .SpaceX.API.Device.WifiConfig.BasicServiceSet basic_service_sets = 1007
  bool client_isolation = 1008
  bool guest = 1009
  string landing = 1010
  string domain = 1011
  uint32 dhcpv4_start = 1012
  bool internal = 1013
  uint32 vlan = 1014
  bool dhcp_disabled = 1015
  uint32 dhcpv4_lease_duration_s = 1016
  bool landing_page_v2 = 1017
  bool sandbox_enabled = 1020
  string sandbox_domain_allow_list = 1022
  uint32 sandbox_id = 1023
  .SpaceX.API.Device.CaptivePortal captive_portal = 1024
  uint32 dhcpv4_end = 1025
  uint32 network_groups = 1026
  .SpaceX.API.Device.WifiConfig.DnsStaticEntry dns_static_entries = 1027
  .SpaceX.API.Device.WifiConfig.DnsForwardRule dns_forward_rules = 1028
  bool disable_when_offline_old = 1029
  .SpaceX.API.Device.WifiConfig.StaticRoute static_routes = 1030
  bool disable_when_offline = 1031
  .SpaceX.API.Device.TlsConfig onboard_radius_tls_config_old = 1032
  .SpaceX.API.Device.TlsConfig onboard_radius_tls_config = 1033
  bool dns_disabled = 1034
  bool get_lease_dhcp = 1035
  bool default_route_disabled = 1036
  .SpaceX.API.Device.WifiConfig.Network.GeofenceAction geofence_action = 1038
SpaceX.API.Device.HttpServer
  string domain_name = 1
  .SpaceX.API.Device.TlsConfig tls = 2
  string file_content_id = 3
  string file_content_hash = 4
  string access_control_allow_origins = 5
SpaceX.API.Device.WifiConfig.UnbridgedEthPort
  uint32 lan_port_index = 1
  string ip = 2
  string gateway = 3
  .SpaceX.API.Device.WifiConfig.UnbridgedEthPort.StaticRoute static_routes = 4
  .SpaceX.API.Device.WanNone wan_none = 5
  .SpaceX.API.Device.WanStarlinkRouterPair wan_starlink_router_pair = 6
  uint32 bridged_network_group_override = 7
  string subnet = 1
  uint32 network_groups = 2
SpaceX.API.Device.WifiConfig.MultiTenantRole
SpaceX.API.Device.NoTrafficControl
SpaceX.API.Device.AckSuppression
  uint32 ack_mark = 1
  float htb_ack_queue_rate = 2
  float htb_ack_queue_ceil = 3
  float cake_queue_bandwidth = 4
  bool cake_ack_filter_aggressive = 5
  float cake_manual_rtt = 6
SpaceX.API.Device.CakeRateLimit
  uint32 host_mark = 1
  float bandwidth = 2
  .SpaceX.API.Device.CakePriorityQueueParameter priority_queue_parameter = 3
  .SpaceX.API.Device.CakeAckFilter ack_filter = 4
  float manual_rtt = 6
SpaceX.API.Device.WifiConfig.Band
SpaceX.API.Device.AuthOpen
SpaceX.API.Device.AuthWpa2
  string password = 1
SpaceX.API.Device.AuthWpa3
  string password = 1
SpaceX.API.Device.AuthWpa2Wpa3
  string password = 1
SpaceX.API.Device.AuthRadius
  string server = 1
  string password = 2
  string server_ca = 3
  string server_ca_base_64 = 4
  .SpaceX.API.Device.Protocol transport = 5
SpaceX.API.Device.AuthOpenEncrypted
SpaceX.API.Device.AuthOnboardRadius
SpaceX.API.Device.WifiConfig.BasicServiceSet
  string bssid = 1003
  string ssid = 1005
  .SpaceX.API.Device.WifiConfig.Band band = 1011
  bool disable = 1013
  bool hidden = 1015
  string iface_name = 1017
  .SpaceX.API.Device.AuthOpen auth_open = 2001
  .SpaceX.API.Device.AuthWpa2 auth_wpa2 = 2002
  .SpaceX.API.Device.AuthWpa3 auth_wpa3 = 2003
  .SpaceX.API.Device.AuthWpa2Wpa3 auth_wpa2_wpa3 = 2004
  .SpaceX.API.Device.AuthRadius auth_radius = 2005
  .SpaceX.API.Device.AuthOpenEncrypted auth_open_encrypted = 2006
  .SpaceX.API.Device.AuthOnboardRadius auth_onboard_radius = 2007
SpaceX.API.Device.CaptivePortal
  string url = 1
  bool display_in_captive_browser = 2
SpaceX.API.Device.WifiConfig.DnsStaticEntry
  string domains = 1000
  string addresses = 1001
SpaceX.API.Device.WifiConfig.DnsForwardRule
  string domains = 1000
  string server_addresses = 1001
SpaceX.API.Device.WifiConfig.StaticRoute
  string subnet = 1
  string gateway = 2
```

### Read-only response checks

- get_device_info: RPC_OR_DESCRIPTION_OK
  Recognized response payloads: apiVersion, getDeviceInfo
```text
response.apiVersion: str (value withheld)
response.getDeviceInfo.deviceInfo.antiRollbackVersion: int (value withheld)
response.getDeviceInfo.deviceInfo.boardRev: int (value withheld)
response.getDeviceInfo.deviceInfo.boot.apiVersionEvenSide: int (value withheld)
response.getDeviceInfo.deviceInfo.boot.apiVersionOddSide: int (value withheld)
response.getDeviceInfo.deviceInfo.boot.countByReason.[unrecognized-or-map-key]: int (value withheld)
response.getDeviceInfo.deviceInfo.boot.countByReason: object
response.getDeviceInfo.deviceInfo.boot.evenSideSoftwareVersion: str (value withheld)
response.getDeviceInfo.deviceInfo.boot.lastCount: int (value withheld)
response.getDeviceInfo.deviceInfo.boot.lastReason: str (value withheld)
response.getDeviceInfo.deviceInfo.boot.oddSideSoftwareVersion: str (value withheld)
response.getDeviceInfo.deviceInfo.boot: object
response.getDeviceInfo.deviceInfo.bootcount: int (value withheld)
response.getDeviceInfo.deviceInfo.countryCode: str (value withheld)
response.getDeviceInfo.deviceInfo.hardwareIndex: str (value withheld)
response.getDeviceInfo.deviceInfo.hardwareVersion: str (value withheld)
response.getDeviceInfo.deviceInfo.id: str (value withheld)
response.getDeviceInfo.deviceInfo.inactiveAntiRollbackVersion: int (value withheld)
response.getDeviceInfo.deviceInfo.manufacturedVersion: str (value withheld)
response.getDeviceInfo.deviceInfo.softwarePartitionsEqual: bool (value withheld)
response.getDeviceInfo.deviceInfo.softwareVersion: str (value withheld)
response.getDeviceInfo.deviceInfo: object
response.getDeviceInfo: object
response: object
```
- get_status: RPC_OR_DESCRIPTION_OK
  Recognized response payloads: apiVersion, wifiGetStatus
```text
response.apiVersion: str (value withheld)
response.wifiGetStatus.alerts: object
response.wifiGetStatus.calibrationPartitionsState: str (value withheld)
response.wifiGetStatus.clientIndex: int (value withheld)
response.wifiGetStatus.clients: array (length 11)
response.wifiGetStatus.clients[].active: bool (value withheld)
response.wifiGetStatus.clients[].alerts: object
response.wifiGetStatus.clients[].associatedTimeS: int (value withheld)
response.wifiGetStatus.clients[].captiveClientId: str (value withheld)
response.wifiGetStatus.clients[].channelWidth: int (value withheld)
response.wifiGetStatus.clients[].clientId: int (value withheld)
response.wifiGetStatus.clients[].deviceId: str (value withheld)
response.wifiGetStatus.clients[].dhcpLeaseActive: bool (value withheld)
response.wifiGetStatus.clients[].dhcpLeaseFound: bool (value withheld)
response.wifiGetStatus.clients[].dhcpLeaseRenewed: bool (value withheld)
response.wifiGetStatus.clients[].domain: str (value withheld)
response.wifiGetStatus.clients[].dot11vSupport: bool (value withheld)
response.wifiGetStatus.clients[].downloadMb: int (value withheld)
response.wifiGetStatus.clients[].givenName: str (value withheld)
response.wifiGetStatus.clients[].hopsFromController: int (value withheld)
response.wifiGetStatus.clients[].iface: str (value withheld)
response.wifiGetStatus.clients[].ifaceName: str (value withheld)
response.wifiGetStatus.clients[].ipAddress: str (value withheld)
response.wifiGetStatus.clients[].ipv6Addresses: array (length 1)
response.wifiGetStatus.clients[].ipv6Addresses: array (length 2)
response.wifiGetStatus.clients[].ipv6Addresses: array (length 3)
response.wifiGetStatus.clients[].ipv6Addresses: array (length 5)
response.wifiGetStatus.clients[].ipv6Addresses: array (length 6)
response.wifiGetStatus.clients[].ipv6Addresses[]: str (value withheld)
response.wifiGetStatus.clients[].macAddress: str (value withheld)
response.wifiGetStatus.clients[].name: str (value withheld)
response.wifiGetStatus.clients[].noDataIdleS: int (value withheld)
response.wifiGetStatus.clients[].powerSaveMode: int (value withheld)
response.wifiGetStatus.clients[].powerSaveModeCount: int (value withheld)
response.wifiGetStatus.clients[].powerSaveModeDurationMs: str (value withheld)
response.wifiGetStatus.clients[].role: str (value withheld)
response.wifiGetStatus.clients[].rxStats.bandwidth: int (value withheld)
response.wifiGetStatus.clients[].rxStats.bytes: str (value withheld)
response.wifiGetStatus.clients[].rxStats.guardNs: int (value withheld)
response.wifiGetStatus.clients[].rxStats.mcs: int (value withheld)
response.wifiGetStatus.clients[].rxStats.nss: int (value withheld)
response.wifiGetStatus.clients[].rxStats.phyMode: int (value withheld)
response.wifiGetStatus.clients[].rxStats.rateMbps: int (value withheld)
response.wifiGetStatus.clients[].rxStats.rateMbpsLast15s: float (value withheld)
response.wifiGetStatus.clients[].rxStats.rateMbpsLast15s: int (value withheld)
response.wifiGetStatus.clients[].rxStats.rateMbpsLast1mAvg: float (value withheld)
response.wifiGetStatus.clients[].rxStats.rateMbpsLast1mAvg: int (value withheld)
response.wifiGetStatus.clients[].rxStats.throughputMbpsLast15sAvg: float (value withheld)
response.wifiGetStatus.clients[].rxStats.throughputMbpsLast1mAvg: float (value withheld)
response.wifiGetStatus.clients[].rxStats: object
response.wifiGetStatus.clients[].rxStatsValid: bool (value withheld)
response.wifiGetStatus.clients[].secondsUntilDhcpLeaseExpires: float (value withheld)
response.wifiGetStatus.clients[].signalStrength: int (value withheld)
response.wifiGetStatus.clients[].snr: int (value withheld)
response.wifiGetStatus.clients[].steerState: int (value withheld)
response.wifiGetStatus.clients[].txStats.bandwidth: int (value withheld)
response.wifiGetStatus.clients[].txStats.bytes: str (value withheld)
response.wifiGetStatus.clients[].txStats.guardNs: int (value withheld)
response.wifiGetStatus.clients[].txStats.mcs: int (value withheld)
response.wifiGetStatus.clients[].txStats.nss: int (value withheld)
response.wifiGetStatus.clients[].txStats.phyMode: int (value withheld)
response.wifiGetStatus.clients[].txStats.rateMbps: int (value withheld)
response.wifiGetStatus.clients[].txStats.rateMbpsLast15s: float (value withheld)
response.wifiGetStatus.clients[].txStats.rateMbpsLast15s: int (value withheld)
response.wifiGetStatus.clients[].txStats.rateMbpsLast30s: float (value withheld)
response.wifiGetStatus.clients[].txStats.rateMbpsLast30s: int (value withheld)
response.wifiGetStatus.clients[].txStats.throughputMbpsLast15sAvg: float (value withheld)
response.wifiGetStatus.clients[].txStats: object
response.wifiGetStatus.clients[].txStatsValid: bool (value withheld)
response.wifiGetStatus.clients[].uploadMb: int (value withheld)
response.wifiGetStatus.clients[].upstreamMacAddress: str (value withheld)
response.wifiGetStatus.clients[]: object
response.wifiGetStatus.config.boot.apiVersionEvenSide: int (value withheld)
response.wifiGetStatus.config.boot.apiVersionOddSide: int (value withheld)
response.wifiGetStatus.config.boot.countByReason.[unrecognized-or-map-key]: int (value withheld)
response.wifiGetStatus.config.boot.countByReason: object
response.wifiGetStatus.config.boot.evenSideSoftwareVersion: str (value withheld)
response.wifiGetStatus.config.boot.lastCount: int (value withheld)
response.wifiGetStatus.config.boot.lastReason: str (value withheld)
response.wifiGetStatus.config.boot.oddSideSoftwareVersion: str (value withheld)
response.wifiGetStatus.config.boot: object
response.wifiGetStatus.config.bootCount: int (value withheld)
response.wifiGetStatus.config.clientConfigs: array (length 5)
response.wifiGetStatus.config.clientConfigs[].clientId: int (value withheld)
response.wifiGetStatus.config.clientConfigs[].givenName: str (value withheld)
response.wifiGetStatus.config.clientConfigs[].macAddress: str (value withheld)
response.wifiGetStatus.config.clientConfigs[]: object
response.wifiGetStatus.config.countryCode: str (value withheld)
response.wifiGetStatus.config.incarnation: str (value withheld)
response.wifiGetStatus.config.macLan: str (value withheld)
response.wifiGetStatus.config.macWan: str (value withheld)
response.wifiGetStatus.config.networks: array (length 1)
response.wifiGetStatus.config.networks[].basicServiceSets: array (length 3)
response.wifiGetStatus.config.networks[].basicServiceSets[].authWpa2.password: str (value withheld)
response.wifiGetStatus.config.networks[].basicServiceSets[].authWpa2: object
response.wifiGetStatus.config.networks[].basicServiceSets[].band: str (value withheld)
response.wifiGetStatus.config.networks[].basicServiceSets[].bssid: str (value withheld)
response.wifiGetStatus.config.networks[].basicServiceSets[].ifaceName: str (value withheld)
response.wifiGetStatus.config.networks[].basicServiceSets[].ssid: str (value withheld)
response.wifiGetStatus.config.networks[].basicServiceSets[]: object
response.wifiGetStatus.config.networks[].dhcpv4End: int (value withheld)
response.wifiGetStatus.config.networks[].dhcpv4LeaseDurationS: int (value withheld)
response.wifiGetStatus.config.networks[].dhcpv4Start: int (value withheld)
response.wifiGetStatus.config.networks[].domain: str (value withheld)
response.wifiGetStatus.config.networks[].ipv4: str (value withheld)
response.wifiGetStatus.config.networks[].vlan: int (value withheld)
response.wifiGetStatus.config.networks[]: object
response.wifiGetStatus.config.setupComplete: bool (value withheld)
response.wifiGetStatus.config.wanAckSuppression.cakeAckFilterAggressive: bool (value withheld)
response.wifiGetStatus.config.wanAckSuppression.cakeQueueBandwidth: float (value withheld)
response.wifiGetStatus.config.wanAckSuppression.htbAckQueueCeil: float (value withheld)
response.wifiGetStatus.config.wanAckSuppression.htbAckQueueRate: int (value withheld)
response.wifiGetStatus.config.wanAckSuppression: object
response.wifiGetStatus.config.wanHostDscpMark: int (value withheld)
response.wifiGetStatus.config: object
response.wifiGetStatus.deviceInfo.antiRollbackVersion: int (value withheld)
response.wifiGetStatus.deviceInfo.boardRev: int (value withheld)
response.wifiGetStatus.deviceInfo.boot.apiVersionEvenSide: int (value withheld)
response.wifiGetStatus.deviceInfo.boot.apiVersionOddSide: int (value withheld)
response.wifiGetStatus.deviceInfo.boot.countByReason.[unrecognized-or-map-key]: int (value withheld)
response.wifiGetStatus.deviceInfo.boot.countByReason: object
response.wifiGetStatus.deviceInfo.boot.evenSideSoftwareVersion: str (value withheld)
response.wifiGetStatus.deviceInfo.boot.lastCount: int (value withheld)
response.wifiGetStatus.deviceInfo.boot.lastReason: str (value withheld)
response.wifiGetStatus.deviceInfo.boot.oddSideSoftwareVersion: str (value withheld)
response.wifiGetStatus.deviceInfo.boot: object
response.wifiGetStatus.deviceInfo.bootcount: int (value withheld)
response.wifiGetStatus.deviceInfo.countryCode: str (value withheld)
response.wifiGetStatus.deviceInfo.hardwareIndex: str (value withheld)
response.wifiGetStatus.deviceInfo.hardwareVersion: str (value withheld)
response.wifiGetStatus.deviceInfo.id: str (value withheld)
response.wifiGetStatus.deviceInfo.inactiveAntiRollbackVersion: int (value withheld)
response.wifiGetStatus.deviceInfo.manufacturedVersion: str (value withheld)
response.wifiGetStatus.deviceInfo.softwarePartitionsEqual: bool (value withheld)
response.wifiGetStatus.deviceInfo.softwareVersion: str (value withheld)
response.wifiGetStatus.deviceInfo: object
response.wifiGetStatus.deviceState.uptimeS: str (value withheld)
response.wifiGetStatus.deviceState: object
response.wifiGetStatus.dhcpServers: array (length 3)
response.wifiGetStatus.dhcpServers[].domain: str (value withheld)
response.wifiGetStatus.dhcpServers[].leases: array (length 15)
response.wifiGetStatus.dhcpServers[].leases[].active: bool (value withheld)
response.wifiGetStatus.dhcpServers[].leases[].clientId: int (value withheld)
response.wifiGetStatus.dhcpServers[].leases[].expiresTime: str (value withheld)
response.wifiGetStatus.dhcpServers[].leases[].hostname: str (value withheld)
response.wifiGetStatus.dhcpServers[].leases[].ipAddress: str (value withheld)
response.wifiGetStatus.dhcpServers[].leases[].macAddress: str (value withheld)
response.wifiGetStatus.dhcpServers[].leases[]: object
response.wifiGetStatus.dhcpServers[].subnet: str (value withheld)
response.wifiGetStatus.dhcpServers[]: object
response.wifiGetStatus.dishDisablementCode: str (value withheld)
response.wifiGetStatus.dishId: str (value withheld)
response.wifiGetStatus.dishPingLatencyMs: float (value withheld)
response.wifiGetStatus.hasClientIndex: bool (value withheld)
response.wifiGetStatus.ipv4WanAddress: str (value withheld)
response.wifiGetStatus.ipv6WanAddresses: array (length 2)
response.wifiGetStatus.ipv6WanAddresses[]: str (value withheld)
response.wifiGetStatus.pingLatencyMs: float (value withheld)
response.wifiGetStatus.poeStats.poePower: float (value withheld)
response.wifiGetStatus.poeStats.poeState: str (value withheld)
response.wifiGetStatus.poeStats.vsnsVin: float (value withheld)
response.wifiGetStatus.poeStats: object
response.wifiGetStatus.popIpv6PingLatencyMs: float (value withheld)
response.wifiGetStatus.popPingLatencyMs: float (value withheld)
response.wifiGetStatus.publicIpv4: str (value withheld)
response.wifiGetStatus.radiusStats: object
response.wifiGetStatus.secsSinceLastPublicIpv4Change: float (value withheld)
response.wifiGetStatus.setupRequirement: object
response.wifiGetStatus.softwareUpdateStats.runningVersion: str (value withheld)
response.wifiGetStatus.softwareUpdateStats.secondsSinceGetTargetVersions: float (value withheld)
response.wifiGetStatus.softwareUpdateStats.state: str (value withheld)
response.wifiGetStatus.softwareUpdateStats: object
response.wifiGetStatus.utcNs: str (value withheld)
response.wifiGetStatus: object
response: object
```
- get_history: RPC_OR_DESCRIPTION_OK
  Recognized response payloads: apiVersion, wifiGetHistory
```text
response.apiVersion: str (value withheld)
response.wifiGetHistory.cloudflareIpv4PingDropRateLast15s: array (length 60)
response.wifiGetHistory.cloudflareIpv4PingDropRateLast15s: first 25 elements inspected
response.wifiGetHistory.cloudflareIpv4PingDropRateLast15s[]: int (value withheld)
response.wifiGetHistory.cloudflareIpv6PingDropRateLast15s: array (length 60)
response.wifiGetHistory.cloudflareIpv6PingDropRateLast15s: first 25 elements inspected
response.wifiGetHistory.cloudflareIpv6PingDropRateLast15s[]: int (value withheld)
response.wifiGetHistory.current: str (value withheld)
response.wifiGetHistory.currentIndex15s: str (value withheld)
response.wifiGetHistory.dnsResolverDropRate.[unrecognized-or-map-key].dropRateLast15s: array (length 60)
response.wifiGetHistory.dnsResolverDropRate.[unrecognized-or-map-key].dropRateLast15s: first 25 elements inspected
response.wifiGetHistory.dnsResolverDropRate.[unrecognized-or-map-key].dropRateLast15s[]: int (value withheld)
response.wifiGetHistory.dnsResolverDropRate.[unrecognized-or-map-key].dropRateLast15s[]: str (value withheld)
response.wifiGetHistory.dnsResolverDropRate.[unrecognized-or-map-key]: object
response.wifiGetHistory.dnsResolverDropRate: object
response.wifiGetHistory.eventLog.currentTimestampNs: str (value withheld)
response.wifiGetHistory.eventLog.events: array (length 15)
response.wifiGetHistory.eventLog.events[].[unrecognized-or-map-key].[unrecognized-or-map-key]: str (value withheld)
response.wifiGetHistory.eventLog.events[].[unrecognized-or-map-key].clientId: int (value withheld)
response.wifiGetHistory.eventLog.events[].[unrecognized-or-map-key]: object
response.wifiGetHistory.eventLog.events[].[unrecognized-or-map-key]: str (value withheld)
response.wifiGetHistory.eventLog.events[].deviceId: str (value withheld)
response.wifiGetHistory.eventLog.events[].startTimestampNs: str (value withheld)
response.wifiGetHistory.eventLog.events[]: object
response.wifiGetHistory.eventLog.startTimestampNs: str (value withheld)
response.wifiGetHistory.eventLog: object
response.wifiGetHistory.googleIpv4PingDropRateLast15s: array (length 60)
response.wifiGetHistory.googleIpv4PingDropRateLast15s: first 25 elements inspected
response.wifiGetHistory.googleIpv4PingDropRateLast15s[]: int (value withheld)
response.wifiGetHistory.googleIpv6PingDropRateLast15s: array (length 60)
response.wifiGetHistory.googleIpv6PingDropRateLast15s: first 25 elements inspected
response.wifiGetHistory.googleIpv6PingDropRateLast15s[]: int (value withheld)
response.wifiGetHistory.pingDropRate: array (length 43200)
response.wifiGetHistory.pingDropRate: first 25 elements inspected
response.wifiGetHistory.pingDropRate[]: int (value withheld)
response.wifiGetHistory.pingLatencyMs: array (length 43200)
response.wifiGetHistory.pingLatencyMs: first 25 elements inspected
response.wifiGetHistory.pingLatencyMs[]: float (value withheld)
response.wifiGetHistory.popIpv4PingDropRateLast15s: array (length 60)
response.wifiGetHistory.popIpv4PingDropRateLast15s: first 25 elements inspected
response.wifiGetHistory.popIpv4PingDropRateLast15s[]: int (value withheld)
response.wifiGetHistory.popIpv6PingDropRateLast15s: array (length 60)
response.wifiGetHistory.popIpv6PingDropRateLast15s: first 25 elements inspected
response.wifiGetHistory.popIpv6PingDropRateLast15s[]: int (value withheld)
response.wifiGetHistory: object
response: object
```
- wifi_get_clients: RPC_OR_DESCRIPTION_OK
  Recognized response payloads: apiVersion, wifiGetClients
```text
response.apiVersion: str (value withheld)
response.wifiGetClients.clientIndex: int (value withheld)
response.wifiGetClients.clients: array (length 11)
response.wifiGetClients.clients[].active: bool (value withheld)
response.wifiGetClients.clients[].alerts: object
response.wifiGetClients.clients[].associatedTimeS: int (value withheld)
response.wifiGetClients.clients[].captiveClientId: str (value withheld)
response.wifiGetClients.clients[].channelWidth: int (value withheld)
response.wifiGetClients.clients[].clientId: int (value withheld)
response.wifiGetClients.clients[].deviceId: str (value withheld)
response.wifiGetClients.clients[].dhcpLeaseActive: bool (value withheld)
response.wifiGetClients.clients[].dhcpLeaseFound: bool (value withheld)
response.wifiGetClients.clients[].dhcpLeaseRenewed: bool (value withheld)
response.wifiGetClients.clients[].domain: str (value withheld)
response.wifiGetClients.clients[].dot11vSupport: bool (value withheld)
response.wifiGetClients.clients[].downloadMb: int (value withheld)
response.wifiGetClients.clients[].givenName: str (value withheld)
response.wifiGetClients.clients[].hopsFromController: int (value withheld)
response.wifiGetClients.clients[].iface: str (value withheld)
response.wifiGetClients.clients[].ifaceName: str (value withheld)
response.wifiGetClients.clients[].ipAddress: str (value withheld)
response.wifiGetClients.clients[].ipv6Addresses: array (length 1)
response.wifiGetClients.clients[].ipv6Addresses: array (length 2)
response.wifiGetClients.clients[].ipv6Addresses: array (length 3)
response.wifiGetClients.clients[].ipv6Addresses: array (length 5)
response.wifiGetClients.clients[].ipv6Addresses: array (length 6)
response.wifiGetClients.clients[].ipv6Addresses[]: str (value withheld)
response.wifiGetClients.clients[].macAddress: str (value withheld)
response.wifiGetClients.clients[].name: str (value withheld)
response.wifiGetClients.clients[].noDataIdleS: int (value withheld)
response.wifiGetClients.clients[].powerSaveMode: int (value withheld)
response.wifiGetClients.clients[].powerSaveModeCount: int (value withheld)
response.wifiGetClients.clients[].powerSaveModeDurationMs: str (value withheld)
response.wifiGetClients.clients[].role: str (value withheld)
response.wifiGetClients.clients[].rxStats.bandwidth: int (value withheld)
response.wifiGetClients.clients[].rxStats.bytes: str (value withheld)
response.wifiGetClients.clients[].rxStats.guardNs: int (value withheld)
response.wifiGetClients.clients[].rxStats.mcs: int (value withheld)
response.wifiGetClients.clients[].rxStats.nss: int (value withheld)
response.wifiGetClients.clients[].rxStats.phyMode: int (value withheld)
response.wifiGetClients.clients[].rxStats.rateMbps: int (value withheld)
response.wifiGetClients.clients[].rxStats.rateMbpsLast15s: float (value withheld)
response.wifiGetClients.clients[].rxStats.rateMbpsLast15s: int (value withheld)
response.wifiGetClients.clients[].rxStats.rateMbpsLast1mAvg: float (value withheld)
response.wifiGetClients.clients[].rxStats.rateMbpsLast1mAvg: int (value withheld)
response.wifiGetClients.clients[].rxStats.throughputMbpsLast15sAvg: float (value withheld)
response.wifiGetClients.clients[].rxStats.throughputMbpsLast1mAvg: float (value withheld)
response.wifiGetClients.clients[].rxStats: object
response.wifiGetClients.clients[].rxStatsValid: bool (value withheld)
response.wifiGetClients.clients[].secondsUntilDhcpLeaseExpires: float (value withheld)
response.wifiGetClients.clients[].signalStrength: int (value withheld)
response.wifiGetClients.clients[].snr: int (value withheld)
response.wifiGetClients.clients[].steerState: int (value withheld)
response.wifiGetClients.clients[].txStats.bandwidth: int (value withheld)
response.wifiGetClients.clients[].txStats.bytes: str (value withheld)
response.wifiGetClients.clients[].txStats.guardNs: int (value withheld)
response.wifiGetClients.clients[].txStats.mcs: int (value withheld)
response.wifiGetClients.clients[].txStats.nss: int (value withheld)
response.wifiGetClients.clients[].txStats.phyMode: int (value withheld)
response.wifiGetClients.clients[].txStats.rateMbps: int (value withheld)
response.wifiGetClients.clients[].txStats.rateMbpsLast15s: float (value withheld)
response.wifiGetClients.clients[].txStats.rateMbpsLast15s: int (value withheld)
response.wifiGetClients.clients[].txStats.rateMbpsLast30s: float (value withheld)
response.wifiGetClients.clients[].txStats.rateMbpsLast30s: int (value withheld)
response.wifiGetClients.clients[].txStats.throughputMbpsLast15sAvg: float (value withheld)
response.wifiGetClients.clients[].txStats: object
response.wifiGetClients.clients[].txStatsValid: bool (value withheld)
response.wifiGetClients.clients[].uploadMb: int (value withheld)
response.wifiGetClients.clients[].upstreamMacAddress: str (value withheld)
response.wifiGetClients.clients[]: object
response.wifiGetClients.hasClientIndex: bool (value withheld)
response.wifiGetClients: object
response: object
```
Client records returned: 11; identity/OS not inferred.
User-specified Windows IP matched records: 1
- client-1-history: RPC_OR_DESCRIPTION_OK
  Recognized response payloads: apiVersion, wifiGetClientHistory
```text
response.apiVersion: str (value withheld)
response.wifiGetClientHistory.current: str (value withheld)
response.wifiGetClientHistory.rxThroughputMbps: array (length 900)
response.wifiGetClientHistory.rxThroughputMbps: first 25 elements inspected
response.wifiGetClientHistory.rxThroughputMbps[]: int (value withheld)
response.wifiGetClientHistory.txThroughputMbps: array (length 900)
response.wifiGetClientHistory.txThroughputMbps: first 25 elements inspected
response.wifiGetClientHistory.txThroughputMbps[]: int (value withheld)
response.wifiGetClientHistory: object
response: object
```
## Dish

TCP reachable from this host: yes. This alone does not confirm API access.
Reflection listing: RPC_OR_DESCRIPTION_OK

### Reflected field definitions

Only field names/types below; no personal response values.

```text
SpaceX.API.Device.Request
  uint64 id = 1
  string target_id = 13
  uint64 epoch_id = 14
  .SpaceX.API.Device.SignedData signed_request = 15
  .SpaceX.API.Device.RebootRequest reboot = 1001
  .SpaceX.API.Device.SpeedTestRequest speed_test = 1003
  .SpaceX.API.Device.GetStatusRequest get_status = 1004
  .SpaceX.API.Device.AuthenticateRequest authenticate = 1005
  .SpaceX.API.Device.GetNextIdRequest get_next_id = 1006
  .SpaceX.API.Device.GetHistoryRequest get_history = 1007
  .SpaceX.API.Device.GetDeviceInfoRequest get_device_info = 1008
  .SpaceX.API.Device.GetPingRequest get_ping = 1009
  .SpaceX.API.Device.SetTrustedKeysRequest set_trusted_keys = 1010
  .SpaceX.API.Device.FactoryResetRequest factory_reset = 1011
  .SpaceX.API.Device.GetLogRequest get_log = 1012
  .SpaceX.API.Device.SetSkuRequest set_sku = 1013
  .SpaceX.API.Device.UpdateRequest update = 1014
  .SpaceX.API.Device.GetNetworkInterfacesRequest get_network_interfaces = 1015
  .SpaceX.API.Device.PingHostRequest ping_host = 1016
  .SpaceX.API.Device.GetLocationRequest get_location = 1017
  .SpaceX.API.Device.GetHeapDumpRequest get_heap_dump = 1019
  .SpaceX.API.Device.RestartControlRequest restart_control = 1020
  .SpaceX.API.Device.FuseRequest fuse = 1021
  .SpaceX.API.Device.GetPersistentStatsRequest get_persistent_stats = 1022
  .SpaceX.API.Device.GetConnectionsRequest get_connections = 1023
  .SpaceX.API.Device.StartSpeedtestRequest start_speedtest = 1027
  .SpaceX.API.Device.GetSpeedtestStatusRequest get_speedtest_status = 1028
  .SpaceX.API.Device.ReportClientSpeedtestRequest report_client_speedtest = 1029
  .SpaceX.API.Device.InitiateRemoteSshRequest initiate_remote_ssh = 1030
  .SpaceX.API.Device.SelfTestRequest self_test = 1031
  .SpaceX.API.Device.SetTestModeRequest set_test_mode = 1032
  .SpaceX.API.Device.SoftwareUpdateRequest software_update = 1033
  .SpaceX.API.Device.EnableDebugTelemRequest enable_debug_telem = 1034
  .SpaceX.API.Device.IQCaptureRequest iq_capture = 1035
  .SpaceX.API.Device.GetRadioStatsRequest get_radio_stats = 1036
  .SpaceX.API.Device.GetTimeRequest time = 1037
  .SpaceX.API.Device.RunIperfServerRequest run_iperf_server = 1038
  .SpaceX.API.Device.TcpConnectivityTestRequest tcp_connectivity_test = 1039
  .SpaceX.API.Device.UdpConnectivityTestRequest udp_connectivity_test = 1040
  .SpaceX.API.Device.GetGoroutineStackTracesRequest get_goroutine_stack_traces = 1041
  .SpaceX.API.Device.SignedData sensitive_request = 1078
  .SpaceX.API.Device.DishStowRequest dish_stow = 2002
  .SpaceX.API.Device.DishGetContextRequest dish_get_context = 2003
  .SpaceX.API.Device.DishSetEmcRequest dish_set_emc = 2007
  .SpaceX.API.Device.DishGetObstructionMapRequest dish_get_obstruction_map = 2008
  .SpaceX.API.Device.DishGetEmcRequest dish_get_emc = 2009
  .SpaceX.API.Device.DishSetConfigRequest dish_set_config = 2010
  .SpaceX.API.Device.DishGetConfigRequest dish_get_config = 2011
  .SpaceX.API.Device.DishPowerSaveRequest dish_power_save = 2013
  .SpaceX.API.Device.DishInhibitGpsRequest dish_inhibit_gps = 2014
  .SpaceX.API.Device.DishGetDataRequest dish_get_data = 2015
  .SpaceX.API.Device.DishClearObstructionMapRequest dish_clear_obstruction_map = 2017
  .SpaceX.API.Device.DishSetMaxPowerTestModeRequest dish_set_max_power_test_mode = 2018
  .SpaceX.API.Device.DishActivateRssiScanRequest dish_activate_rssi_scan = 2019
  .SpaceX.API.Device.DishGetRssiScanResultRequest dish_get_rssi_scan_result = 2020
  .SpaceX.API.Device.DishFactoryResetRequest dish_factory_reset = 2021
  .SpaceX.API.Device.ResetButtonRequest reset_button = 2022
  .SpaceX.API.Device.SoftwareUpdateRequest set_per_vehicle_config = 2023
  .SpaceX.API.Device.DishAviationTestRequest dish_aviation_test = 2024
  .SpaceX.API.Device.DishInhibitRfRequest dish_inhibit_rf = 2026
  .SpaceX.API.Device.ZtlmQueryRequest ztlm_query = 2027
  .SpaceX.API.Device.DishStartTestModeServerRequest dish_start_test_mode_server = 2028
  .SpaceX.API.Device.UserReportedIssueRequest user_reported_issue = 2029
  .SpaceX.API.Device.WifiSetConfigRequest wifi_set_config = 3001
  .SpaceX.API.Device.WifiGetClientsRequest wifi_get_clients = 3002
  .SpaceX.API.Device.WifiSetupRequest wifi_setup = 3003
  .SpaceX.API.Device.WifiGetPingMetricsRequest wifi_get_ping_metrics = 3007
  .SpaceX.API.Device.WifiGetConfigRequest wifi_get_config = 3009
  .SpaceX.API.Device.WifiSetMeshDeviceTrustRequest wifi_set_mesh_device_trust = 3012
  .SpaceX.API.Device.WifiSetMeshConfigRequest wifi_set_mesh_config = 3013
  .SpaceX.API.Device.WifiGetClientHistoryRequest wifi_get_client_history = 3015
  .SpaceX.API.Device.WifiSetAviationConformedRequest wifi_set_aviation_conformed = 3016
  .SpaceX.API.Device.WifiSetClientGivenNameRequest wifi_set_client_given_name = 3017
  .SpaceX.API.Device.WifiSelfTestRequest wifi_self_test = 3018
  .SpaceX.API.Device.WifiCalibrationModeRequest wifi_calibration_mode = 3019
  .SpaceX.API.Device.WifiGuestInfoRequest wifi_guest_info = 3020
  .SpaceX.API.Device.WifiRfTestRequest wifi_rf_test = 3021
  .SpaceX.API.Device.WifiGetFirewallRequest wifi_get_firewall = 3024
  .SpaceX.API.Device.WifiTogglePoeNegotiationRequest wifi_toggle_poe_negotiation = 3025
  .SpaceX.API.Device.WifiFactoryTestCommandRequest wifi_factory_test_command = 3026
  .SpaceX.API.Device.WifiStartLocalTelemProxyRequest wifi_start_local_telem_proxy = 3027
  .SpaceX.API.Device.WifiRunSelfTestRequest wifi_run_self_test = 3028
  .SpaceX.API.Device.WifiBackhaulStatsRequest wifi_backhaul_stats = 3029
  .SpaceX.API.Device.WifiToggleUmbilicalModeRequest wifi_toggle_umbilical_mode = 3030
  .SpaceX.API.Device.WifiClientSandboxRequest wifi_client_sandbox = 3031
  .SpaceX.API.Device.WifiRunDebugNetsysRequest wifi_run_debug_netsys = 3032
  .SpaceX.API.Device.WifiResetEthPhyRequest wifi_reset_eth_phy = 3033
  .SpaceX.API.Device.WifiFlushHardwareNatRequest wifi_flush_hardware_nat = 3034
  .SpaceX.API.Device.WifiWriteCalibrationRequest wifi_write_calibration = 3035
  .SpaceX.API.Device.WifiStartTracerouteRequest wifi_start_traceroute = 3036
  .SpaceX.API.Device.WifiGetTracerouteStatusRequest wifi_get_traceroute_status = 3037
  .SpaceX.API.Device.TransceiverIFLoopbackTestRequest transceiver_if_loopback_test = 4001
  .SpaceX.API.Device.TransceiverGetStatusRequest transceiver_get_status = 4003
  .SpaceX.API.Device.TransceiverGetTelemetryRequest transceiver_get_telemetry = 4004
  .SpaceX.API.Device.Services.Unlock.StartUnlockRequest start_unlock = 5000
  .SpaceX.API.Device.Services.Unlock.FinishUnlockRequest finish_unlock = 5001
  .SpaceX.API.Device.GetDiagnosticsRequest get_diagnostics = 6000
  .SpaceX.API.Device.GetGnssMeasurementRequest get_gnss_measurement = 7000
  .SpaceX.API.Device.ToggleModeRequest toggle_mode = 7001
  .SpaceX.API.Device.GetToggleModeRequest toggle_mode_status = 7002
SpaceX.API.Device.Response
  uint64 id = 1
  .SpaceX.API.Status.Status status = 2
  uint64 api_version = 3
  .SpaceX.API.Device.RebootResponse reboot = 1001
  .SpaceX.API.Device.SpeedTestResponse speed_test = 1003
  .SpaceX.API.Device.GetDeviceInfoResponse get_device_info = 1004
  .SpaceX.API.Device.GetNextIdResponse get_next_id = 1006
  .SpaceX.API.Device.GetPingResponse get_ping = 1009
  .SpaceX.API.Device.SetTrustedKeysResponse set_trusted_keys = 1010
  .SpaceX.API.Device.FactoryResetResponse factory_reset = 1011
  .SpaceX.API.Device.GetLogResponse get_log = 1012
  .SpaceX.API.Device.SetSkuResponse set_sku = 1013
  .SpaceX.API.Device.UpdateResponse update = 1014
  .SpaceX.API.Device.GetNetworkInterfacesResponse get_network_interfaces = 1015
  .SpaceX.API.Device.PingHostResponse ping_host = 1016
  .SpaceX.API.Device.GetLocationResponse get_location = 1017
  .SpaceX.API.Device.GetHeapDumpResponse get_heap_dump = 1019
  .SpaceX.API.Device.RestartControlResponse restart_control = 1020
  .SpaceX.API.Device.FuseResponse fuse = 1021
  .SpaceX.API.Device.GetConnectionsResponse get_connections = 1023
  .SpaceX.API.Device.StartSpeedtestResponse start_speedtest = 1027
  .SpaceX.API.Device.GetSpeedtestStatusResponse get_speedtest_status = 1028
  .SpaceX.API.Device.ReportClientSpeedtestResponse report_client_speedtest = 1029
  .SpaceX.API.Device.InitiateRemoteSshResponse initiate_remote_ssh = 1030
  .SpaceX.API.Device.SelfTestResponse self_test = 1031
  .SpaceX.API.Device.SetTestModeResponse set_test_mode = 1032
  .SpaceX.API.Device.SoftwareUpdateResponse software_update = 1033
  .SpaceX.API.Device.EnableDebugTelemResponse enable_debug_telem = 1034
  .SpaceX.API.Device.GetRadioStatsResponse get_radio_stats = 1035
  .SpaceX.API.Device.GetTimeResponse time = 1037
  .SpaceX.API.Device.RunIperfServerResponse run_iperf_server = 1038
  .SpaceX.API.Device.GetGoroutineStackTracesResponse get_goroutine_stack_traces = 1041
  .SpaceX.API.Device.DishStowResponse dish_stow = 2002
  .SpaceX.API.Device.DishGetContextResponse dish_get_context = 2003
  .SpaceX.API.Device.DishGetStatusResponse dish_get_status = 2004
  .SpaceX.API.Device.DishAuthenticateResponse dish_authenticate = 2005
  .SpaceX.API.Device.DishGetHistoryResponse dish_get_history = 2006
  .SpaceX.API.Device.DishSetEmcResponse dish_set_emc = 2007
  .SpaceX.API.Device.DishGetObstructionMapResponse dish_get_obstruction_map = 2008
  .SpaceX.API.Device.DishGetEmcResponse dish_get_emc = 2009
  .SpaceX.API.Device.DishSetConfigResponse dish_set_config = 2010
  .SpaceX.API.Device.DishGetConfigResponse dish_get_config = 2011
  .SpaceX.API.Device.DishInhibitGpsResponse dish_inhibit_gps = 2013
  .SpaceX.API.Device.DishClearObstructionMapResponse dish_clear_obstruction_map = 2015
  .SpaceX.API.Device.DishSetMaxPowerTestModeResponse dish_set_max_power_test_mode = 2018
  .SpaceX.API.Device.DishActivateRssiScanResponse dish_activate_rssi_scan = 2019
  .SpaceX.API.Device.DishGetRssiScanResultResponse dish_get_rssi_scan_result = 2020
  .SpaceX.API.Device.DishFactoryResetResponse dish_factory_reset = 2021
  .SpaceX.API.Device.ResetButtonResponse reset_button = 2022
  .SpaceX.API.Device.SetPerVehicleConfigResponse set_per_vehicle_config = 2023
  .SpaceX.API.Device.DishAviationTestResponse dish_aviation_test = 2024
  .SpaceX.API.Device.DishInhibitRfResponse dish_inhibit_rf = 2026
  .SpaceX.API.Device.ZtlmQueryResponse ztlm_query = 2027
  .SpaceX.API.Device.DishStartTestModeServerResponse dish_start_test_mode_server = 2028
  .SpaceX.API.Device.UserReportedIssueResponse user_reported_issue = 2029
  .SpaceX.API.Device.WifiSetConfigResponse wifi_set_config = 3001
  .SpaceX.API.Device.WifiGetClientsResponse wifi_get_clients = 3002
  .SpaceX.API.Device.WifiSetupResponse wifi_setup = 3003
  .SpaceX.API.Device.WifiGetStatusResponse wifi_get_status = 3004
  .SpaceX.API.Device.WifiAuthenticateResponse wifi_authenticate = 3005
  .SpaceX.API.Device.WifiGetHistoryResponse wifi_get_history = 3006
  .SpaceX.API.Device.WifiGetPingMetricsResponse wifi_get_ping_metrics = 3007
  .SpaceX.API.Device.WifiGetConfigResponse wifi_get_config = 3009
  .SpaceX.API.Device.WifiSetMeshDeviceTrustResponse wifi_set_mesh_device_trust = 3012
  .SpaceX.API.Device.WifiSetMeshConfigResponse wifi_set_mesh_config = 3013
  .SpaceX.API.Device.WifiGetClientHistoryResponse wifi_get_client_history = 3015
  .SpaceX.API.Device.WifiSelfTestResponse wifi_self_test = 3016
  .SpaceX.API.Device.WifiGuestInfoResponse wifi_guest_info = 3020
  .SpaceX.API.Device.WifiRfTestResponse wifi_rf_test = 3021
  .SpaceX.API.Device.WifiGetPersistentStatsResponse wifi_get_persistent_stats = 3022
  .SpaceX.API.Device.WifiGetFirewallResponse wifi_get_firewall = 3024
  .SpaceX.API.Device.WifiFactoryTestCommandResponse wifi_factory_test_command = 3025
  .SpaceX.API.Device.WifiBackhaulStatsResponse wifi_backhaul_stats = 3026
  .SpaceX.API.Device.WifiClientSandboxResponse wifi_client_sandbox = 3027
  .SpaceX.API.Device.WifiUpdateResponse wifi_update = 3028
  .SpaceX.API.Device.WifiRunDebugNetsysResponse wifi_run_debug_netsys = 3029
  .SpaceX.API.Device.WifiResetEthPhyResponse wifi_reset_eth_phy = 3030
  .SpaceX.API.Device.WifiFlushHardwareNatResponse wifi_flush_hardware_nat = 3031
  .SpaceX.API.Device.WifiGetTracerouteStatusResponse wifi_get_traceroute_status = 3032
  .SpaceX.API.Device.TransceiverIFLoopbackTestResponse transceiver_if_loopback_test = 4001
  .SpaceX.API.Device.TransceiverGetStatusResponse transceiver_get_status = 4003
  .SpaceX.API.Device.TransceiverGetTelemetryResponse transceiver_get_telemetry = 4004
  .SpaceX.API.Device.Services.Unlock.StartUnlockResponse start_unlock = 5000
  .SpaceX.API.Device.Services.Unlock.FinishUnlockResponse finish_unlock = 5001
  .SpaceX.API.Device.WifiGetDiagnosticsResponse wifi_get_diagnostics = 6000
  .SpaceX.API.Device.DishGetDiagnosticsResponse dish_get_diagnostics = 6001
  .SpaceX.API.Device.GetGnssMeasurementResponse get_gnss_measurement = 7000
  .SpaceX.API.Device.ToggleModeResponse toggle_mode = 7001
  .SpaceX.API.Device.GetToggleModeResponse toggle_mode_status = 7002
SpaceX.API.Device.GetDeviceInfoResponse
  .SpaceX.API.Device.DeviceInfo device_info = 1
SpaceX.API.Device.DeviceInfo
  string id = 1
  string hardware_version = 2
  string software_version = 3
  string country_code = 4
  int32 utc_offset_s = 5
  bool software_partitions_equal = 6
  bool is_dev = 7
  int32 bootcount = 8
  int32 anti_rollback_version = 9
  bool is_hitl = 10
  string manufactured_version = 11
  int64 generation_number = 12
  bool dish_cohoused = 13
  int32 board_rev = 14
  string build_id = 15
  .SpaceX.API.Device.HardwareIndex hardware_index = 16
  .SpaceX.API.Device.BootInfo boot = 1001
SpaceX.API.Device.GetConnectionsResponse
  map<string, .SpaceX.API.Device.GetConnectionsResponse.ServiceConnection> services = 1
  string address = 1
  int32 seconds_since_success = 2
SpaceX.API.Device.DishGetStatusResponse
  .SpaceX.API.Device.DeviceInfo device_info = 1
  .SpaceX.API.Device.DeviceState device_state = 2
  float seconds_to_first_nonempty_slot = 1002
  float pop_ping_drop_rate = 1003
  .SpaceX.API.Device.DishObstructionStats obstruction_stats = 1004
  .SpaceX.API.Device.DishAlerts alerts = 1005
  float downlink_throughput_bps = 1007
  float uplink_throughput_bps = 1008
  float pop_ping_latency_ms = 1009
  bool stow_requested = 1010
  float boresight_azimuth_deg = 1011
  float boresight_elevation_deg = 1012
  .SpaceX.API.Device.DishOutage outage = 1014
  .SpaceX.API.Device.DishGpsStats gps_stats = 1015
  int32 eth_speed_mbps = 1016
  .SpaceX.API.Device.UserMobilityClass mobility_class = 1017
  bool is_snr_above_noise_floor = 1018
  .SpaceX.API.Device.DishReadyStates ready_states = 1019
  .SpaceX.API.Device.UserClassOfService class_of_service = 1020
  .SpaceX.API.Device.SoftwareUpdateState software_update_state = 1021
  bool is_snr_persistently_low = 1022
  .SpaceX.API.Device.HasActuators has_actuators = 1023
  .SpaceX.API.Satellites.Network.UtDisablementCode disablement_code = 1024
  bool has_signed_cals = 1025
  .SpaceX.API.Device.SoftwareUpdateStats software_update_stats = 1026
  .SpaceX.API.Device.AlignmentStats alignment_stats = 1027
  .SpaceX.API.Device.InitializationDurationSeconds initialization_duration_seconds = 1028
  bool is_cell_disabled = 1029
  bool swupdate_reboot_ready = 1030
  int32 seconds_until_swupdate_reboot_possible = 1031
  .SpaceX.API.Device.RebootReason reboot_reason = 1032
  bool high_power_test_mode = 1033
  string connected_routers = 1040
  .SpaceX.API.Device.PLCStats plc_stats = 1041
  bool is_moving_fast_persisted = 1042
  .SpaceX.API.Device.DishUpsuStats upsu_stats = 1043
  .SpaceX.API.Telemetron.Public.Integrations.RateLimitReason dl_bandwidth_restricted_reason = 1044
  .SpaceX.API.Telemetron.Public.Integrations.RateLimitReason ul_bandwidth_restricted_reason = 1045
  .SpaceX.API.Device.DishApsStats aps_stats = 1048
  .SpaceX.API.Device.Quaternion ned2dish_quaternion = 1049
  map<string, .SpaceX.API.Device.RouterInfo> downstream_routers = 1050
  .SpaceX.API.Device.AccountShard account_shard = 1051
  bool mac_flag = 1052
  .SpaceX.API.Device.NatFlag nat_flag = 1053
  .SpaceX.API.Device.DishBatteryStats battery_stats = 1054
  bool user_debug_mode_enabled = 1055
  bool treat_as_metered = 1056
  float signal_quality = 1057
  .SpaceX.API.Device.DishConfig config = 2000
SpaceX.API.Device.DishGetHistoryResponse
  uint64 current = 1
  float pop_ping_drop_rate = 1001
  float pop_ping_latency_ms = 1002
  float downlink_throughput_bps = 1003
  float uplink_throughput_bps = 1004
  .SpaceX.API.Device.DishOutage outages = 1009
  float power_in = 1010
  .SpaceX.API.Device.EventLog event_log = 1011
SpaceX.API.Device.GetConnectionsRequest
SpaceX.API.Device.WifiGetClientHistoryRequest
  string mac_address = 1
  uint32 client_id = 2
SpaceX.API.Device.WifiGetClientHistoryResponse
  uint64 current = 1
  float tx_throughput_mbps = 2
  float rx_throughput_mbps = 3
  .SpaceX.API.Device.WifiGetClientHistoryResponse.WifiLimitedReason throughput_limited = 4
  float rx_rate_mbps = 5
  bytes rssi = 6
SpaceX.API.Device.HardwareIndex
SpaceX.API.Device.BootInfo
  map<int32, int32> count_by_reason = 1
  .SpaceX.API.Device.BootReason last_reason = 2
  int32 last_count = 3
  map<int32, int32> count_by_reason_delta = 4
  bool crash_boot = 5
  int32 crash_boot_count = 6
  string even_side_software_version = 7
  string odd_side_software_version = 8
  int32 api_version_odd_side = 9
  int32 api_version_even_side = 10
SpaceX.API.Device.DeviceState
  uint64 uptime_s = 1
SpaceX.API.Device.DishObstructionStats
  float fraction_obstructed = 1
  float valid_s = 4
  bool currently_obstructed = 5
  float avg_prolonged_obstruction_duration_s = 6
  float avg_prolonged_obstruction_interval_s = 7
  bool avg_prolonged_obstruction_valid = 8
  float time_obstructed = 9
  uint32 patches_valid = 10
SpaceX.API.Device.DishAlerts
  bool motors_stuck = 1
  bool thermal_shutdown = 2
  bool thermal_throttle = 3
  bool unexpected_location = 4
  bool mast_not_near_vertical = 5
  bool slow_ethernet_speeds = 6
  bool install_pending = 8
  bool is_heating = 9
  bool power_supply_thermal_throttle = 10
  bool is_power_save_idle = 11
  bool dbf_telem_stale = 14
  bool low_motor_current = 16
  bool lower_signal_than_predicted = 17
  bool slow_ethernet_speeds_100 = 18
  bool obstruction_map_reset = 19
  bool dish_water_detected = 20
  bool router_water_detected = 21
  bool upsu_router_port_slow = 22
  bool no_ethernet_link = 23
SpaceX.API.Device.DishOutage
  .SpaceX.API.Device.DishOutage.Cause cause = 1
  int64 start_timestamp_ns = 2
  uint64 duration_ns = 3
  bool did_switch = 4
SpaceX.API.Device.DishGpsStats
  bool gps_valid = 1
  uint32 gps_sats = 2
  bool no_sats_after_ttff = 3
  bool inhibit_gps = 4
  .SpaceX.API.Device.AttitudeEstimationState pnt_filter_convergence_state = 5
SpaceX.API.Device.UserMobilityClass
SpaceX.API.Device.DishReadyStates
  bool cady = 1
  bool scp = 2
  bool l1l2 = 3
  bool xphy = 4
  bool aap = 5
  bool rf = 6
SpaceX.API.Device.UserClassOfService
SpaceX.API.Device.SoftwareUpdateState
SpaceX.API.Device.HasActuators
SpaceX.API.Device.SoftwareUpdateStats
  .SpaceX.API.Device.SoftwareUpdateState software_update_state = 1
  float software_update_progress = 2
  bool update_requires_reboot = 3
  int64 reboot_scheduled_utc_time = 4
SpaceX.API.Device.AlignmentStats
  .SpaceX.API.Device.HasActuators has_actuators = 1
  .SpaceX.API.Device.ActuatorState actuator_state = 2
  float tilt_angle_deg = 3
  float boresight_azimuth_deg = 4
  float boresight_elevation_deg = 5
  .SpaceX.API.Device.AttitudeEstimationState attitude_estimation_state = 6
  float attitude_uncertainty_deg = 7
  float desired_boresight_azimuth_deg = 8
  float desired_boresight_elevation_deg = 9
SpaceX.API.Device.InitializationDurationSeconds
  int32 attitude_initialization = 1
  int32 burst_detected = 2
  int32 ekf_converged = 3
  int32 first_cplane = 4
  int32 first_pop_ping = 5
  int32 gps_valid = 6
  int32 initial_network_entry = 7
  int32 network_schedule = 8
  int32 rf_ready = 9
  int32 stable_connection = 10
SpaceX.API.Device.RebootReason
SpaceX.API.Device.PLCStats
  bool receiving_plc = 1
  uint32 average_time_to_empty = 2
  uint32 average_time_to_full = 3
  uint32 battery_health = 4
  uint32 hardware_revision_id = 5
  bool permanent_failure = 6
  .SpaceX.API.Device.PLCPortStats port_1_stats = 7
  .SpaceX.API.Device.PLCPortStats port_2_stats = 8
  .SpaceX.API.Device.PLCPortStats port_3_stats = 9
  .SpaceX.API.Device.PLCStats.ProtocolRevision plc_revision = 10
  bool safety_mode_active = 11
  uint32 state_of_charge = 12
  uint32 thermal_throttle_level = 13
SpaceX.API.Device.DishUpsuStats
  uint64 app_version = 2
  uint64 boot_version = 3
  uint64 rom_version = 4
  int64 uptime = 5
  float dish_power = 6
  float router_power = 7
  bool force_dev_signed_allowed = 8
  bool debug_port_locked = 9
  bool stsafe_certs_locked = 10
  bool stsafe_keys_locked = 11
  uint32 g0_locked = 12
  uint32 g0_firmware_version = 13
  int32 board_rev = 14
  uint32 g0_board_id = 15
SpaceX.API.Device.DishApsStats
  uint64 app_version = 2
  uint64 boot_version = 3
  uint64 rom_version = 4
  int64 uptime = 5
  float dish_power = 6
  bool force_dev_signed_allowed = 7
  bool debug_port_locked = 8
  int32 board_rev = 9
SpaceX.API.Device.Quaternion
  float q_scalar = 1
  float q_x = 2
  float q_y = 3
  float q_z = 4
SpaceX.API.Device.AccountShard
SpaceX.API.Device.NatFlag
SpaceX.API.Device.DishBatteryStats
  uint32 state_of_charge = 1
  bool is_charging = 2
  .SpaceX.API.Device.PowerSource power_source = 3
SpaceX.API.Device.DishConfig
  .SpaceX.API.Device.DishConfig.SnowMeltMode snow_melt_mode = 1
  .SpaceX.API.Device.DishConfig.LocationRequestMode location_request_mode = 2
  .SpaceX.API.Device.DishConfig.LevelDishMode level_dish_mode = 3
  uint32 power_save_start_minutes = 4
  uint32 power_save_duration_minutes = 5
  bool power_save_mode = 6
  bool swupdate_three_day_deferral_enabled = 7
  uint32 asset_class = 8
  uint32 swupdate_reboot_hour = 9
  bool apply_snow_melt_mode = 1001
  bool apply_location_request_mode = 2001
  bool apply_level_dish_mode = 3001
  bool apply_power_save_start_minutes = 4001
  bool apply_power_save_duration_minutes = 5001
  bool apply_power_save_mode = 6001
  bool apply_swupdate_three_day_deferral_enabled = 7001
  bool apply_asset_class = 8001
  bool apply_swupdate_reboot_hour = 9001
SpaceX.API.Device.EventLog
  .SpaceX.API.Device.UXEvent events = 1
  int64 start_timestamp_ns = 2
  int64 current_timestamp_ns = 3
SpaceX.API.Device.WifiGetClientHistoryResponse.WifiLimitedReason
SpaceX.API.Device.BootReason
SpaceX.API.Device.DishOutage.Cause
SpaceX.API.Device.AttitudeEstimationState
SpaceX.API.Device.ActuatorState
SpaceX.API.Device.PLCPortStats
  uint32 power = 1
  .SpaceX.API.Device.PLCPortStats.PortStatus status = 2
SpaceX.API.Device.PLCStats.ProtocolRevision
SpaceX.API.Device.PowerSource
SpaceX.API.Device.DishConfig.SnowMeltMode
SpaceX.API.Device.DishConfig.LocationRequestMode
SpaceX.API.Device.DishConfig.LevelDishMode
SpaceX.API.Device.UXEvent
  .SpaceX.API.Device.EventSeverity severity = 1
  .SpaceX.API.Device.EventReason reason = 2
  int64 start_timestamp_ns = 3
  uint64 duration_ns = 4
  .SpaceX.API.Device.ClientReconnectingOftenMetadata client_reconnecting_often_metadata = 5
  .SpaceX.API.Device.ClientSwitchingBandMetadata client_switching_band_metadata = 6
  .SpaceX.API.Device.ClientSwitchingUpstreamMacMetadata client_switching_upstream_mac_metadata = 7
  .SpaceX.API.Device.MeshConnectionChangingMetadata mesh_connection_changing_metadata = 8
  .SpaceX.API.Device.MeshBackhaulLowPhyMetadata mesh_backhaul_low_phy_metadata = 9
  .SpaceX.API.Device.HighOverlappingBssMetadata high_overlapping_bss_metadata = 10
  .SpaceX.API.Device.ClientExcessiveNetworkConnectionsMetadata client_excessive_network_connections_metadata = 11
  string device_id = 12
SpaceX.API.Device.PLCPortStats.PortStatus
SpaceX.API.Device.EventSeverity
SpaceX.API.Device.EventReason
SpaceX.API.Device.ClientReconnectingOftenMetadata
  uint32 clientId = 1
SpaceX.API.Device.ClientSwitchingBandMetadata
  uint32 clientId = 1
  string fromBand = 2
  string toBand = 3
SpaceX.API.Device.ClientSwitchingUpstreamMacMetadata
  uint32 clientId = 1
SpaceX.API.Device.MeshConnectionChangingMetadata
  string repeaterId = 1
  .SpaceX.API.Device.MeshConnectionChange change = 2
SpaceX.API.Device.MeshBackhaulLowPhyMetadata
  string repeaterIds = 1
SpaceX.API.Device.HighOverlappingBssMetadata
  .SpaceX.API.Device.HighOverlappingBssStats high_overlapping_bss_stats = 1
SpaceX.API.Device.ClientExcessiveNetworkConnectionsMetadata
  uint32 clientId = 1
SpaceX.API.Device.MeshConnectionChange
SpaceX.API.Device.HighOverlappingBssStats
  string iface = 1
  uint32 average_overlapping_bss_percentage = 2
```

### Read-only response checks

- get_device_info: RPC_OR_DESCRIPTION_OK
  Recognized response payloads: apiVersion, getDeviceInfo
```text
response.apiVersion: str (value withheld)
response.getDeviceInfo.deviceInfo.bootcount: int (value withheld)
response.getDeviceInfo.deviceInfo.buildId: str (value withheld)
response.getDeviceInfo.deviceInfo.countryCode: str (value withheld)
response.getDeviceInfo.deviceInfo.generationNumber: str (value withheld)
response.getDeviceInfo.deviceInfo.hardwareVersion: str (value withheld)
response.getDeviceInfo.deviceInfo.id: str (value withheld)
response.getDeviceInfo.deviceInfo.softwareVersion: str (value withheld)
response.getDeviceInfo.deviceInfo.utcOffsetS: int (value withheld)
response.getDeviceInfo.deviceInfo: object
response.getDeviceInfo: object
response: object
```
- get_status: RPC_OR_DESCRIPTION_OK
  Recognized response payloads: apiVersion, dishGetStatus
```text
response.apiVersion: str (value withheld)
response.dishGetStatus.accountShard: str (value withheld)
response.dishGetStatus.alerts: object
response.dishGetStatus.alignmentStats.attitudeEstimationState: str (value withheld)
response.dishGetStatus.alignmentStats.attitudeUncertaintyDeg: float (value withheld)
response.dishGetStatus.alignmentStats.boresightAzimuthDeg: float (value withheld)
response.dishGetStatus.alignmentStats.boresightElevationDeg: float (value withheld)
response.dishGetStatus.alignmentStats.desiredBoresightAzimuthDeg: float (value withheld)
response.dishGetStatus.alignmentStats.desiredBoresightElevationDeg: float (value withheld)
response.dishGetStatus.alignmentStats.hasActuators: str (value withheld)
response.dishGetStatus.alignmentStats.tiltAngleDeg: float (value withheld)
response.dishGetStatus.alignmentStats: object
response.dishGetStatus.apsStats: object
response.dishGetStatus.batteryStats: object
response.dishGetStatus.boresightAzimuthDeg: float (value withheld)
response.dishGetStatus.boresightElevationDeg: float (value withheld)
response.dishGetStatus.classOfService: str (value withheld)
response.dishGetStatus.config.applyAssetClass: bool (value withheld)
response.dishGetStatus.config.applyLevelDishMode: bool (value withheld)
response.dishGetStatus.config.applyLocationRequestMode: bool (value withheld)
response.dishGetStatus.config.applyPowerSaveDurationMinutes: bool (value withheld)
response.dishGetStatus.config.applyPowerSaveMode: bool (value withheld)
response.dishGetStatus.config.applyPowerSaveStartMinutes: bool (value withheld)
response.dishGetStatus.config.applySnowMeltMode: bool (value withheld)
response.dishGetStatus.config.applySwupdateRebootHour: bool (value withheld)
response.dishGetStatus.config.applySwupdateThreeDayDeferralEnabled: bool (value withheld)
response.dishGetStatus.config.powerSaveDurationMinutes: int (value withheld)
response.dishGetStatus.config.powerSaveMode: bool (value withheld)
response.dishGetStatus.config.powerSaveStartMinutes: int (value withheld)
response.dishGetStatus.config.snowMeltMode: str (value withheld)
response.dishGetStatus.config.swupdateRebootHour: int (value withheld)
response.dishGetStatus.config: object
response.dishGetStatus.connectedRouters: array (length 1)
response.dishGetStatus.connectedRouters[]: str (value withheld)
response.dishGetStatus.deviceInfo.bootcount: int (value withheld)
response.dishGetStatus.deviceInfo.buildId: str (value withheld)
response.dishGetStatus.deviceInfo.countryCode: str (value withheld)
response.dishGetStatus.deviceInfo.generationNumber: str (value withheld)
response.dishGetStatus.deviceInfo.hardwareVersion: str (value withheld)
response.dishGetStatus.deviceInfo.id: str (value withheld)
response.dishGetStatus.deviceInfo.softwareVersion: str (value withheld)
response.dishGetStatus.deviceInfo.utcOffsetS: int (value withheld)
response.dishGetStatus.deviceInfo: object
response.dishGetStatus.deviceState.uptimeS: str (value withheld)
response.dishGetStatus.deviceState: object
response.dishGetStatus.disablementCode: str (value withheld)
response.dishGetStatus.dlBandwidthRestrictedReason: str (value withheld)
response.dishGetStatus.downlinkThroughputBps: float (value withheld)
response.dishGetStatus.downstreamRouters.[unrecognized-or-map-key].[unrecognized-or-map-key]: str (value withheld)
response.dishGetStatus.downstreamRouters.[unrecognized-or-map-key]: object
response.dishGetStatus.downstreamRouters: object
response.dishGetStatus.ethSpeedMbps: int (value withheld)
response.dishGetStatus.gpsStats.gpsSats: int (value withheld)
response.dishGetStatus.gpsStats.gpsValid: bool (value withheld)
response.dishGetStatus.gpsStats.pntFilterConvergenceState: str (value withheld)
response.dishGetStatus.gpsStats: object
response.dishGetStatus.hasActuators: str (value withheld)
response.dishGetStatus.hasSignedCals: bool (value withheld)
response.dishGetStatus.initializationDurationSeconds.attitudeInitialization: int (value withheld)
response.dishGetStatus.initializationDurationSeconds.burstDetected: int (value withheld)
response.dishGetStatus.initializationDurationSeconds.ekfConverged: int (value withheld)
response.dishGetStatus.initializationDurationSeconds.firstCplane: int (value withheld)
response.dishGetStatus.initializationDurationSeconds.firstPopPing: int (value withheld)
response.dishGetStatus.initializationDurationSeconds.gpsValid: int (value withheld)
response.dishGetStatus.initializationDurationSeconds.initialNetworkEntry: int (value withheld)
response.dishGetStatus.initializationDurationSeconds.networkSchedule: int (value withheld)
response.dishGetStatus.initializationDurationSeconds.rfReady: int (value withheld)
response.dishGetStatus.initializationDurationSeconds.stableConnection: int (value withheld)
response.dishGetStatus.initializationDurationSeconds: object
response.dishGetStatus.isSnrAboveNoiseFloor: bool (value withheld)
response.dishGetStatus.natFlag: str (value withheld)
response.dishGetStatus.ned2dishQuaternion.qScalar: float (value withheld)
response.dishGetStatus.ned2dishQuaternion.qX: float (value withheld)
response.dishGetStatus.ned2dishQuaternion.qY: float (value withheld)
response.dishGetStatus.ned2dishQuaternion.qZ: float (value withheld)
response.dishGetStatus.ned2dishQuaternion: object
response.dishGetStatus.obstructionStats.avgProlongedObstructionIntervalS: str (value withheld)
response.dishGetStatus.obstructionStats.patchesValid: int (value withheld)
response.dishGetStatus.obstructionStats.timeObstructed: float (value withheld)
response.dishGetStatus.obstructionStats.validS: int (value withheld)
response.dishGetStatus.obstructionStats: object
response.dishGetStatus.plcStats.port1Stats: object
response.dishGetStatus.plcStats.port2Stats: object
response.dishGetStatus.plcStats.port3Stats: object
response.dishGetStatus.plcStats: object
response.dishGetStatus.popPingLatencyMs: float (value withheld)
response.dishGetStatus.readyStates.aap: bool (value withheld)
response.dishGetStatus.readyStates.l1l2: bool (value withheld)
response.dishGetStatus.readyStates.rf: bool (value withheld)
response.dishGetStatus.readyStates.scp: bool (value withheld)
response.dishGetStatus.readyStates.xphy: bool (value withheld)
response.dishGetStatus.readyStates: object
response.dishGetStatus.secondsToFirstNonemptySlot: float (value withheld)
response.dishGetStatus.secondsUntilSwupdateRebootPossible: int (value withheld)
response.dishGetStatus.signalQuality: int (value withheld)
response.dishGetStatus.softwareUpdateState: str (value withheld)
response.dishGetStatus.softwareUpdateStats.softwareUpdateProgress: int (value withheld)
response.dishGetStatus.softwareUpdateStats.softwareUpdateState: str (value withheld)
response.dishGetStatus.softwareUpdateStats: object
response.dishGetStatus.ulBandwidthRestrictedReason: str (value withheld)
response.dishGetStatus.uplinkThroughputBps: float (value withheld)
response.dishGetStatus.upsuStats: object
response.dishGetStatus: object
response: object
```
- get_history: RPC_OR_DESCRIPTION_OK
  Recognized response payloads: apiVersion, dishGetHistory
```text
response.apiVersion: str (value withheld)
response.dishGetHistory.current: str (value withheld)
response.dishGetHistory.downlinkThroughputBps: array (length 900)
response.dishGetHistory.downlinkThroughputBps: first 25 elements inspected
response.dishGetHistory.downlinkThroughputBps[]: float (value withheld)
response.dishGetHistory.eventLog.currentTimestampNs: str (value withheld)
response.dishGetHistory.eventLog.events: array (length 64)
response.dishGetHistory.eventLog.events: first 25 elements inspected
response.dishGetHistory.eventLog.events[].deviceId: str (value withheld)
response.dishGetHistory.eventLog.events[].durationNs: str (value withheld)
response.dishGetHistory.eventLog.events[].reason: str (value withheld)
response.dishGetHistory.eventLog.events[].severity: str (value withheld)
response.dishGetHistory.eventLog.events[].startTimestampNs: str (value withheld)
response.dishGetHistory.eventLog.events[]: object
response.dishGetHistory.eventLog.startTimestampNs: str (value withheld)
response.dishGetHistory.eventLog: object
response.dishGetHistory.outages: array (length 7)
response.dishGetHistory.outages[].cause: str (value withheld)
response.dishGetHistory.outages[].didSwitch: bool (value withheld)
response.dishGetHistory.outages[].durationNs: str (value withheld)
response.dishGetHistory.outages[].startTimestampNs: str (value withheld)
response.dishGetHistory.outages[]: object
response.dishGetHistory.popPingDropRate: array (length 900)
response.dishGetHistory.popPingDropRate: first 25 elements inspected
response.dishGetHistory.popPingDropRate[]: float (value withheld)
response.dishGetHistory.popPingDropRate[]: int (value withheld)
response.dishGetHistory.popPingLatencyMs: array (length 900)
response.dishGetHistory.popPingLatencyMs: first 25 elements inspected
response.dishGetHistory.popPingLatencyMs[]: float (value withheld)
response.dishGetHistory.powerIn: array (length 900)
response.dishGetHistory.powerIn: first 25 elements inspected
response.dishGetHistory.powerIn[]: float (value withheld)
response.dishGetHistory.uplinkThroughputBps: array (length 900)
response.dishGetHistory.uplinkThroughputBps: first 25 elements inspected
response.dishGetHistory.uplinkThroughputBps[]: float (value withheld)
response.dishGetHistory.uplinkThroughputBps[]: int (value withheld)
response.dishGetHistory: object
response: object
```

## Interpretation limits

- Preserve distinction between schema fields, accepted RPCs and populated response fields.
- Wi-Fi link rate is not internet throughput. Client byte counters may include LAN traffic.
- A field named domain or get_connections is not proof of destination/browsing history.
- Destination attribution requires a client-linked remote IP/domain plus timing evidence.
- Process attribution requires actual process evidence; do not infer it from bandwidth.
- This probe does not invoke arbitrary logs, config, dumps, control or unknown requests.
- No complete absence claim follows from this bounded probe, permission errors, empty data or missing reflection.

Share REPORT.md only. PRIVATE_RAW.json contains unredacted local evidence.
