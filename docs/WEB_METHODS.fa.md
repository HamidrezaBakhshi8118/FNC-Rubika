# فهرست متدهای وب روبیکا

۲۰۵ نام از فایل عمومی وب؛ تأیید schema و عملکرد حساب‌دار هنوز کامل نیست.

کلیدهای جدول فقط موارد ساده مشاهده‌شده هستند، نه schema کامل یا اجباری.

| متد | مسیر | نوع | کلیدهای مشاهده‌شده |
| --- | --- | --- | --- |
| `abortSetRecoveryEmail` | api | mutation | password |
| `abortTwoStepSetup` | api | mutation | — |
| `actionOnJoinRequest` | api | mutation | — |
| `actionOnMessageReaction` | api | mutation | — |
| `actionOnStickerSet` | api | mutation | action, sticker_set_id |
| `actionOnUnconfirmedSession` | api | mutation | action, unconfirmed_session_key |
| `addAddressBook` | api | mutation | — |
| `addChannel` | api | mutation | — |
| `addChannelMembers` | api | mutation | channel_guid, member_guids |
| `addFolder` | api | mutation | — |
| `addGroup` | api | mutation | — |
| `addGroupMembers` | api | mutation | group_guid, member_guids |
| `addLiveComment` | api | mutation | — |
| `addSetWallpaper` | api | mutation | main_file_id, thumbnail_file_id |
| `addToMyGifSet` | api | mutation | message_id, object_guid |
| `banChannelMember` | api | mutation | action, channel_guid, member_guid |
| `banGroupMember` | api | mutation | action, group_guid, member_guid |
| `cancelChangeObjectOwner` | api | mutation | object_guid |
| `changePassword` | api | mutation | — |
| `channelPreviewByJoinLink` | api | read | hash_link |
| `checkChannelUsername` | api | read | username |
| `checkTwoStepPasscode` | api | read | password |
| `checkUserUsername` | api | read | username |
| `clearDrafts` | api | mutation | action, object_guid |
| `clickMessageUrl` | api | mutation | — |
| `createGroupVoiceChat` | api | mutation | chat_guid |
| `createJoinLink` | api | mutation | — |
| `createPoll` | api | mutation | — |
| `deleteAvatar` | api | mutation | avatar_id, object_guid |
| `deleteBotChat` | api | mutation | bot_guid, last_deleted_message_id |
| `deleteChatHistory` | api | mutation | last_message_id, object_guid |
| `deleteContact` | api | mutation | user_guid |
| `deleteFolder` | api | mutation | folder_id |
| `deleteMessages` | api | mutation | — |
| `deleteNoAccessGroupChat` | api | mutation | group_guid |
| `deleteRevokedJoinLink` | api | mutation | — |
| `deleteServiceChat` | api | mutation | last_deleted_message_id, service_guid |
| `deleteUserChat` | api | mutation | last_deleted_message_id, user_guid |
| `discardGroupVoiceChat` | api | mutation | chat_guid, voice_chat_id |
| `editChannelInfo` | api | mutation | — |
| `editFolder` | api | mutation | — |
| `editGroupInfo` | api | mutation | — |
| `editJoinLink` | api | mutation | — |
| `editMessage` | api | mutation | — |
| `forwardMessages` | api | mutation | — |
| `getAbsObjects` | api | read | objects_guids |
| `getAllDrafts` | api | read | — |
| `getAppearanceSetting` | api | read | — |
| `getAvailableReactions` | api | read | — |
| `getAvatars` | api | read | object_guid |
| `getBannedChannelMembers` | api | read | channel_guid, search_text, start_id |
| `getBannedGroupMembers` | api | read | group_guid, search_text, start_id |
| `getBarcodeAction` | api | read | — |
| `getBaseInfo` | api | read | — |
| `getBlockedUsers` | api | read | start_id |
| `getBotInfo` | api | read | bot_guid |
| `getChannelAdminAccessList` | api | read | channel_guid, member_guid |
| `getChannelAdminMembers` | api | read | channel_guid, search_text, start_id |
| `getChannelAllMembers` | api | read | channel_guid, search_text, start_id |
| `getChannelInfo` | api | read | channel_guid |
| `getChannelLink` | api | read | channel_guid |
| `getChatAds` | api | read | state |
| `getChatReaction` | api | read | — |
| `getChats` | api | read | start_id |
| `getChatsByID` | api | read | object_guids |
| `getChatsUpdates` | api | read | state |
| `getCommonGroups` | api | read | user_guid |
| `getContacts` | api | read | start_id |
| `getContactsLastOnline` | api | read | user_guids |
| `getContactsUpdates` | api | read | state |
| `getDCs` | api | read | — |
| `getDisplayAsInGroupVoiceChat` | api | read | chat_guid, start_id |
| `getFolders` | api | read | last_state |
| `getGroupAdminAccessList` | api | read | group_guid, member_guid |
| `getGroupAdminMembers` | api | read | group_guid, search_text, start_id |
| `getGroupAllMembers` | api | read | group_guid, search_text, start_id |
| `getGroupDefaultAccess` | api | read | group_guid |
| `getGroupInfo` | api | read | group_guid |
| `getGroupLink` | api | read | group_guid |
| `getGroupMentionList` | api | read | — |
| `getGroupMessageReadParticipants` | api | read | group_guid, message_id |
| `getGroupOnlineCount` | api | read | group_guid |
| `getGroupVoiceChat` | api | read | chat_guid, voice_chat_id |
| `getGroupVoiceChatParticipants` | api | read | chat_guid, start_id, voice_chat_id |
| `getGroupVoiceChatParticipantsByObjectGuids` | api | read | chat_guid, object_guids, voice_chat_id |
| `getGroupVoiceChatUpdates` | api | read | chat_guid, state, voice_chat_id |
| `getJoinLinkUserJoined` | api | read | — |
| `getJoinLinks` | api | read | creator_guid, object_guid |
| `getJoinRequests` | api | read | — |
| `getLandingPage` | api | read | address |
| `getLinkFromAppUrl` | api | read | app_url |
| `getLiveComments` | api | read | — |
| `getLivePlayUrl` | api | read | access_token, live_id |
| `getLiveStatus` | api | read | access_token, live_id |
| `getLiveViewers` | api | read | live_id, start_id |
| `getMapView` | api | read | location |
| `getMessageReactions` | api | read | — |
| `getMessageShareUrl` | api | read | message_id, object_guid |
| `getMessages` | api | read | — |
| `getMessagesByID` | api | read | message_ids, object_guid |
| `getMessagesInterval` | api | read | filter_type, middle_message_id, object_guid |
| `getMessagesUpdates` | api | read | object_guid, state |
| `getMyArchivedStickerSets` | api | read | search_text, start_id |
| `getMyGifSet` | api | read | — |
| `getMySessions` | api | read | — |
| `getMyStickerSets` | api | read | — |
| `getObjectByUsername` | api | read | username |
| `getPaymentInfo` | api | read | payment_id |
| `getPendingObjectOwner` | api | read | object_guid |
| `getPollOptionVoters` | api | read | poll_id, selection_index, start_id |
| `getPollStatus` | api | read | poll_id |
| `getPrivacySetting` | api | read | — |
| `getProfileLinkItems` | api | read | object_guid |
| `getProfilePosts` | rubino | read | equal, limit, max_id, min_id, sort, target_profile_id |
| `getProfilesStoryList` | rubino | read | — |
| `getRelatedObjects` | api | read | object_guid, start_id |
| `getSelection` | bot / dc_url | read | bot_guid, selection_id, start_id |
| `getServiceInfo` | api | read | service_guid |
| `getStickerSetByID` | api | read | sticker_set_id |
| `getStickerSetting` | api | read | — |
| `getStickersByEmoji` | api | read | emoji_character, suggest_by |
| `getStickersBySetIDs` | api | read | sticker_set_ids |
| `getSuggestedFolders` | api | read | — |
| `getTime` | api | read | — |
| `getTranscription` | api | read | message_id, transcription_id |
| `getTrendStickerSets` | api | read | start_id |
| `getTwoPasscodeStatus` | api | read | — |
| `getUnconfirmedSessions` | api | read | — |
| `getUserInfo` | api | read | user_guid |
| `getUserSetting` | api | read | — |
| `getWalletTransferMessage` | api | read | — |
| `getWallpapers` | api | read | — |
| `getWebAppFunction` | api | read | app_id |
| `getlinkObject` | api | read | share_string |
| `groupPreviewByJoinLink` | api | read | hash_link |
| `handShake` | WebSocket | mutation | — |
| `joinChannelAction` | api | mutation | action, channel_guid |
| `joinChannelByLink` | api | mutation | hash_link |
| `joinGroup` | api | mutation | hash_link |
| `joinGroupVoiceChat` | api | mutation | — |
| `leaveGroup` | api | mutation | group_guid |
| `leaveGroupVoiceChat` | api | mutation | chat_guid, voice_chat_id |
| `loginDisableTwoStep` | api | mutation | — |
| `loginTwoStepForgetPassword` | api | mutation | phone_number |
| `logout` | api | mutation | — |
| `registerDevice` | api | mutation | — |
| `removeChannel` | api | mutation | channel_guid |
| `removeGroup` | api | mutation | group_guid |
| `replyRequestObjectOwner` | api | mutation | — |
| `reportObject` | api | mutation | — |
| `requestChangeObjectOwner` | api | mutation | — |
| `requestChangePhoneNumber` | api | mutation | new_phone_number |
| `requestDeleteAccount` | api | mutation | — |
| `requestRecoveryEmail` | api | mutation | — |
| `requestSendFile` | api | mutation | file_name, mime, size |
| `resendCodeRecoveryEmail` | api | mutation | password |
| `resetContacts` | api | mutation | — |
| `resetWallpapers` | api | mutation | — |
| `revokeJoinLink` | api | mutation | join_link, object_guid |
| `searchChatMessages` | api | read | — |
| `searchGlobalMessages` | api | read | — |
| `searchGlobalObjects` | api | read | — |
| `searchSelection` | bot / dc_url | read | bot_guid, limit, search_text, selection_id |
| `searchStickers` | api | read | search_text, start_id |
| `seenChats` | api | mutation | — |
| `sendChatActivity` | api | mutation | activity, object_guid |
| `sendCode` | api | mutation | — |
| `sendGroupVoiceChatActivity` | api | mutation | — |
| `sendLive` | api | mutation | — |
| `sendMessage` | api | mutation | — |
| `sendMessageAPICall` | bot | mutation | — |
| `sendRubinoPost` | api | mutation | — |
| `sendWalletTransferMessage` | api | mutation | — |
| `setActionChat` | api | mutation | action, duration, object_guid |
| `setAskSpamAction` | api | mutation | — |
| `setBlockUser` | api | mutation | action, user_guid |
| `setChannelAdmin` | api | mutation | — |
| `setChannelLink` | api | mutation | channel_guid |
| `setChatUseTime` | api | mutation | object_guid, time |
| `setGroupAdmin` | api | mutation | — |
| `setGroupDefaultAccess` | api | mutation | access_list, group_guid |
| `setGroupLink` | api | mutation | group_guid |
| `setGroupVoiceChatSetting` | api | mutation | — |
| `setGroupVoiceChatState` | api | mutation | — |
| `setLiveSetting` | api | mutation | — |
| `setPinChatInFolder` | api | mutation | action, folder_id, object_guid |
| `setPinMessage` | api | mutation | — |
| `setPublicKey` | api | mutation | — |
| `setSetting` | api | mutation | settings, update_parameters |
| `setupTwoStepVerification` | api | mutation | — |
| `signIn` | api | mutation | — |
| `stopBot` | api | mutation | bot_guid |
| `stopLive` | api | mutation | live_id |
| `terminateOtherSessions` | api | mutation | — |
| `terminateSession` | api | mutation | session_key |
| `transcribeVoice` | api | mutation | message_id, object_guid |
| `turnOffTwoStep` | api | mutation | password |
| `unregisterDevice` | api | mutation | — |
| `updateChannelUsername` | api | mutation | channel_guid, username |
| `updateProfile` | api | mutation | — |
| `updateUsername` | api | mutation | username |
| `uploadAvatar` | api | mutation | — |
| `verifyChangePhoneNumber` | api | mutation | code, hash |
| `verifyRecoveryEmail` | api | mutation | — |
| `votePoll` | api | mutation | poll_id, selection_index |
